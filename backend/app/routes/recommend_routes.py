"""
Recipe pipeline routes: recommend, next batch, rerank.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import SessionPool, UserPreferences, CookHistory, SavedRecipe
from app.schemas import (
    RecommendRequest, RecommendResponse, NextBatchResponse,
    RerankRequest, RerankResponse, RecipeOut,
)
from app.auth import get_current_user_id
from app.services.pipeline_service import run_pipeline, get_next_batch, rerank_pool, get_pipeline_status

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    req: RecommendRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    prefs_result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = prefs_result.scalar_one_or_none()

    history_result = await db.execute(
        select(CookHistory).where(CookHistory.user_id == user_id)
    )
    history = history_result.scalars().all()

    saved_result = await db.execute(
        select(SavedRecipe).where(SavedRecipe.user_id == user_id)
    )
    saved = saved_result.scalars().all()

    result = await run_pipeline(
        user_id=user_id,
        session_context=req.session_context,
        preferences=prefs,
        history=history,
        saved=saved,
        db=db,
        ranking_mode_override=req.ranking_mode,
    )
    return result


@router.get("/recommend/next", response_model=NextBatchResponse)
async def next_batch(
    session_pool_id: str = Query(..., alias="sessionPoolId"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SessionPool).where(SessionPool.id == session_pool_id)
    )
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Session pool not found")
    if pool.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return await get_next_batch(pool, db)


@router.get("/recommend/status")
async def pipeline_status(
    user_id: str = Depends(get_current_user_id),
):
    """Returns the current pipeline stage for the authenticated user."""
    return get_pipeline_status(user_id)


@router.post("/rerank", response_model=RerankResponse)
async def rerank(
    req: RerankRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SessionPool).where(SessionPool.id == req.session_pool_id)
    )
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Session pool not found")
    if pool.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return await rerank_pool(pool, req.liked_recipe_id, req.action, db)
