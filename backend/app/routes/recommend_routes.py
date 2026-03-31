"""
Recipe recommendation pipeline routes.

Three endpoints orchestrate the full recipe discovery flow:

  POST /api/recommend
    Runs the complete pipeline (ideation → fetch → rank) for a new session.
    Returns the first page of ranked recipes and a session pool ID for
    subsequent pagination calls.

  GET /api/recommend/next
    Returns the next page of recipes from an existing session pool.
    Triggers background re-ideation automatically when the pool runs low.

  GET /api/recommend/status
    Returns the current pipeline progress step for the authenticated user.
    Polled by the "Generating…" screen during the initial pipeline run.

  POST /api/rerank
    Records a user preference signal (saved recipe) against an open pool.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.recommend_routes")

from app.auth import get_current_user_id
from app.database import get_db
from app.models import CookHistory, SavedRecipe, SessionPool, UserPreferences
from app.schemas import (
    NextBatchResponse,
    RecommendRequest,
    RecommendResponse,
    RerankRequest,
    RerankResponse,
)
from app.services.pipeline_service import (
    get_next_batch,
    get_pipeline_status,
    rerank_pool,
    run_pipeline,
)

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post("/recommend", response_model=RecommendResponse)
async def start_recommendation_pipeline(
    req: RecommendRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Run the full recipe recommendation pipeline for a new session.

    Executes all pipeline stages synchronously for the first batch, then
    fires a background task to continue fetching and ranking additional
    recipes. Returns as soon as the first page is ready (~3–8 seconds
    depending on VLM and LLM availability).

    Args:
        req: Request payload containing ``session_context`` (meal type, time,
            ingredients, etc.) and optional ``ranking_mode`` override.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        ``RecommendResponse`` with the first page of ranked recipes, a
        ``session_pool_id`` for pagination, and pipeline metadata.
    """
    user_preferences_result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    user_preferences = user_preferences_result.scalar_one_or_none()

    cook_history_result = await db.execute(
        select(CookHistory).where(CookHistory.user_id == user_id)
    )
    cook_history = cook_history_result.scalars().all()

    saved_recipes_result = await db.execute(
        select(SavedRecipe).where(SavedRecipe.user_id == user_id)
    )
    saved_recipes = saved_recipes_result.scalars().all()

    return await run_pipeline(
        user_id=user_id,
        session_context=req.session_context,
        preferences=user_preferences,
        history=cook_history,
        saved=saved_recipes,
        db=db,
        ranking_mode_override=req.ranking_mode,
    )


@router.get("/recommend/next", response_model=NextBatchResponse)
async def get_next_recipe_page(
    session_pool_id: str = Query(..., alias="sessionPoolId"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the next page of recipes from an existing session pool.

    Advances the pool's shown cursor by one page (5 recipes) and marks the
    returned recipes as shown. Automatically triggers a background re-ideation
    round when fewer than 15 unshown recipes remain in the pool.

    Args:
        session_pool_id: The session pool ID from a prior ``/recommend`` call.
        user_id: Authenticated user's ID — used to verify pool ownership.
        db: Async database session (injected by FastAPI).

    Returns:
        ``NextBatchResponse`` with the next page of ``RecipeOut`` objects.

    Raises:
        HTTPException(404): If the session pool ID is not found.
        HTTPException(403): If the pool belongs to a different user.
    """
    pool_result = await db.execute(
        select(SessionPool).where(SessionPool.id == session_pool_id)
    )
    session_pool = pool_result.scalar_one_or_none()
    if not session_pool:
        raise HTTPException(status_code=404, detail="Session pool not found")
    if session_pool.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    logger.debug(
        "[GET /recommend/next] pool=%s, total_fetched=%s, shown=%s, refetch_count=%s",
        session_pool_id[:8],
        session_pool.total_fetched,
        session_pool.shown_count,
        session_pool.refetch_count,
    )
    result = await get_next_batch(session_pool, db)
    logger.debug(
        "[GET /recommend/next] returning %d recipes, pool_size=%d",
        len(result.recipes), result.pool_size,
    )
    return result


@router.get("/recommend/status")
async def get_recommendation_pipeline_status(
    user_id: str = Depends(get_current_user_id),
):
    """Return the current pipeline progress step for the authenticated user.

    Polled by the frontend "Generating…" screen during the initial pipeline
    run. Returns a step number, human-readable label, and optional detail
    string for display in the progress UI.

    Args:
        user_id: Authenticated user's ID (extracted from JWT by dependency).

    Returns:
        Dict with ``step`` (int), ``label`` (str), ``detail`` (str), and
        ``total_steps`` (int).
    """
    return get_pipeline_status(user_id)


@router.post("/rerank", response_model=RerankResponse)
async def record_recipe_preference_signal(
    req: RerankRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Record a user preference signal (liked/saved recipe) against a pool.

    Updates the session pool to mark the specified recipe as saved and records
    the preference inference string for observability. Future sessions use
    saved recipe history to calibrate LLM re-ranking quality.

    Args:
        req: Contains ``session_pool_id``, ``liked_recipe_id``, and ``action``.
        user_id: Authenticated user's ID — used to verify pool ownership.
        db: Async database session (injected by FastAPI).

    Returns:
        ``RerankResponse`` with a confirmation message and preference note.

    Raises:
        HTTPException(404): If the session pool ID is not found.
        HTTPException(403): If the pool belongs to a different user.
    """
    pool_result = await db.execute(
        select(SessionPool).where(SessionPool.id == req.session_pool_id)
    )
    session_pool = pool_result.scalar_one_or_none()
    if not session_pool:
        raise HTTPException(status_code=404, detail="Session pool not found")
    if session_pool.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return await rerank_pool(session_pool, req.liked_recipe_id, req.action, db)
