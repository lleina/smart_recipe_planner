"""
Recipe pipeline service — orchestrates LLM ideation, web recipe fetch, and ranking.

Stage flow:
  1. Context Assembly  — merge user prefs + session context (done by caller)
  2. LLM Ideation      — generate ~40 recipe name suggestions (llm_service)
  3a. Fast Fetch       — first INITIAL_FETCH_SIZE suggestions resolved before returning
  3b. Background Fetch — remaining suggestions fetched async after response is sent
  4. Initial Ranking   — rule score + optional LLM re-rank on first batch
  5. Serve             — first BATCH_SIZE to client, rest accumulate in session_pool

Ranking mode is set by RecommendRequest.ranking_mode or falls back to
the RANKING_MODE environment variable (default: hybrid).
"""

import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger("app.pipeline")

from app.models import SessionPool, RecipeCache, UserPreferences, CookHistory, SavedRecipe
from app.schemas import (
    SessionContextRequest, RecommendResponse, NextBatchResponse,
    RerankResponse, RecipeOut,
)
from app.services import llm_service, ranking_service, recipe_fetcher
from app.config import RANKING_MODE
from app.database import async_session as db_session_factory

# Cards returned per page (per "Load More")
BATCH_SIZE = 5
# Suggestions resolved before the first response is sent; rest run in background
INITIAL_FETCH_SIZE = 10


async def run_pipeline(
    user_id: str,
    session_context: SessionContextRequest,
    preferences: Optional[UserPreferences],
    history: list[CookHistory],
    saved: list[SavedRecipe],
    db: AsyncSession,
    ranking_mode_override: Optional[str] = None,
) -> RecommendResponse:
    """
    Runs the fast-path pipeline (first INITIAL_FETCH_SIZE suggestions) and immediately
    fires a background task for the remaining suggestions.
    """
    dietary_restrictions = list(preferences.dietary_restrictions or []) if preferences else []
    cuisine_preferences = list(preferences.cuisine_preferences or []) if preferences else []
    cooking_equipment = list(preferences.cooking_equipment or []) if preferences else []
    health_goal = (preferences.health_goal or "none") if preferences else "none"
    history_titles = [h.recipe_id for h in history[:10]]

    # Stage 2: LLM ideation
    logger.info(
        "[%s] Stage 2: LLM ideation (meal=%s, time=%dmin, ingredients=%d)",
        user_id[:8], session_context.meal_type,
        session_context.available_time_minutes,
        len(session_context.available_ingredients),
    )
    suggestions = await llm_service.ideate_recipes(
        context=session_context,
        dietary_restrictions=dietary_restrictions,
        cuisine_preferences=cuisine_preferences,
        health_goal=health_goal,
        history_titles=history_titles,
        cooking_equipment=cooking_equipment,
    )

    first_suggestions = suggestions[:INITIAL_FETCH_SIZE]
    rest_suggestions = suggestions[INITIAL_FETCH_SIZE:]

    # Stage 3a: Fast fetch — first INITIAL_FETCH_SIZE suggestions only
    logger.info(
        "[%s] Stage 3a: fast fetch — %d suggestions (remaining %d deferred to background)",
        user_id[:8], len(first_suggestions), len(rest_suggestions),
    )
    recipes_raw = await recipe_fetcher.fetch_recipes_batch(first_suggestions, session_context, db)

    # Stage 4: Ranking
    effective_mode = ranking_mode_override or RANKING_MODE
    logger.info("[%s] Stage 4: ranking %d recipes (mode=%s)", user_id[:8], len(recipes_raw), effective_mode)
    ranked = await ranking_service.rank_recipes(
        recipes=recipes_raw,
        context=session_context,
        dietary_restrictions=dietary_restrictions,
        cuisine_preferences=cuisine_preferences,
        cooking_equipment=cooking_equipment,
        mode=effective_mode,
    )

    # Deduplicate by ID
    seen_ids: set[str] = set()
    deduped = []
    for r in ranked:
        if r["id"] not in seen_ids:
            deduped.append(r)
            seen_ids.add(r["id"])
    ranked = deduped

    # Stage 5: Persist session pool
    pool_id = str(uuid.uuid4())
    pool_recipes = [
        {
            "recipeId": r["id"],
            "score": r.get("score", 0.0),
            "status": "unshown",
            "shownAt": None,
            "rankPosition": i + 1,
        }
        for i, r in enumerate(ranked)
    ]

    pool = SessionPool(
        id=pool_id,
        user_id=user_id,
        session_id=str(uuid.uuid4()),
        recipes=pool_recipes,
        session_context=session_context.dict(),  # stored for unlimited re-ideation on demand
        total_fetched=len(ranked),
        shown_count=0,
        saved_count=0,
        last_preference_inference=effective_mode,
    )
    db.add(pool)

    for r in ranked:
        cached = RecipeCache(
            id=r["id"],
            title=r["title"],
            description=r.get("description", ""),
            image=r.get("image", ""),
            prep_time=r.get("prep_time", 10),
            cook_time=r.get("cook_time", 25),
            total_time=r.get("total_time", 35),
            difficulty=r.get("difficulty", "medium"),
            servings=r.get("servings", session_context.serving_count),
            cuisine=r.get("cuisine", ""),
            meal_type=r.get("meal_type", [session_context.meal_type]),
            occasions=r.get("occasions", [session_context.occasion] if session_context.occasion else []),
            rating=r.get("rating", 4.0),
            source=r.get("source", "web"),
            source_url=r.get("source_url", ""),
            cooking_equipment=r.get("cooking_equipment", []),
            ingredients=r.get("ingredients", []),
            instructions=r.get("instructions", []),
        )
        await db.merge(cached)

    now = datetime.now(timezone.utc).isoformat()
    for pr in pool_recipes[:BATCH_SIZE]:
        pr["status"] = "shown"
        pr["shownAt"] = now
    pool.shown_count = BATCH_SIZE
    pool.recipes = pool_recipes

    await db.commit()
    await db.refresh(pool)

    logger.info(
        "[%s] Stage 5: pool %s created — %d fast recipes, serving first %d. "
        "Background fetch of %d more suggestions starting.",
        user_id[:8], pool_id[:8], len(ranked), min(BATCH_SIZE, len(ranked)), len(rest_suggestions),
    )

    # Stage 3b: Fire background task for remaining suggestions
    if rest_suggestions:
        asyncio.create_task(
            _background_fetch_and_append(
                pool_id=pool_id,
                suggestions=rest_suggestions,
                session_context=session_context,
                dietary_restrictions=dietary_restrictions,
                cuisine_preferences=cuisine_preferences,
                cooking_equipment=cooking_equipment,
                existing_ids=set(seen_ids),
                ranking_mode=effective_mode,
            )
        )

    return RecommendResponse(
        session_pool_id=pool.id,
        recipes=[_to_out(r) for r in ranked[:BATCH_SIZE]],
        pool_size=len(ranked),
        shown_count=min(BATCH_SIZE, len(ranked)),
        ranking_mode_used=effective_mode,
    )


async def _background_fetch_and_append(
    pool_id: str,
    suggestions: list[dict],
    session_context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    cooking_equipment: list[str],
    existing_ids: set[str],
    ranking_mode: str,
) -> None:
    """
    Background task: fetch + rank remaining suggestions and append them to the pool.
    Uses its own DB session since the request session has already been closed.
    """
    logger.info("[bg/%s] Starting background fetch of %d suggestions", pool_id[:8], len(suggestions))
    try:
        async with db_session_factory() as db:
            recipes_raw = await recipe_fetcher.fetch_recipes_batch(suggestions, session_context, db)

            if not recipes_raw:
                logger.info("[bg/%s] Background fetch returned 0 recipes — nothing to append", pool_id[:8])
                return

            ranked = await ranking_service.rank_recipes(
                recipes=recipes_raw,
                context=session_context,
                dietary_restrictions=dietary_restrictions,
                cuisine_preferences=cuisine_preferences,
                cooking_equipment=cooking_equipment,
                mode=ranking_mode,
            )

            # Fetch pool and append new recipes
            result = await db.execute(select(SessionPool).where(SessionPool.id == pool_id))
            pool = result.scalar_one_or_none()
            if not pool:
                logger.warning("[bg/%s] Pool not found — aborting background append", pool_id[:8])
                return

            current_pool = list(pool.recipes or [])
            current_ids = {r["recipeId"] for r in current_pool} | existing_ids
            new_entries = []

            for r in ranked:
                if r["id"] in current_ids:
                    continue
                current_ids.add(r["id"])
                rank_pos = len(current_pool) + len(new_entries) + 1
                new_entries.append({
                    "recipeId": r["id"],
                    "score": r.get("score", 0.0),
                    "status": "unshown",
                    "shownAt": None,
                    "rankPosition": rank_pos,
                })
                cached = RecipeCache(
                    id=r["id"],
                    title=r["title"],
                    description=r.get("description", ""),
                    image=r.get("image", ""),
                    prep_time=r.get("prep_time", 10),
                    cook_time=r.get("cook_time", 25),
                    total_time=r.get("total_time", 35),
                    difficulty=r.get("difficulty", "medium"),
                    servings=r.get("servings", 4),
                    cuisine=r.get("cuisine", ""),
                    meal_type=r.get("meal_type", [session_context.meal_type]),
                    occasions=r.get("occasions", []),
                    rating=r.get("rating", 4.0),
                    source=r.get("source", "web"),
                    source_url=r.get("source_url", ""),
                    cooking_equipment=r.get("cooking_equipment", []),
                    ingredients=r.get("ingredients", []),
                    instructions=r.get("instructions", []),
                )
                await db.merge(cached)

            if new_entries:
                pool.recipes = current_pool + new_entries
                pool.total_fetched = (pool.total_fetched or 0) + len(new_entries)
                await db.commit()
                logger.info(
                    "[bg/%s] Appended %d more recipes to pool (total=%d)",
                    pool_id[:8], len(new_entries), pool.total_fetched,
                )
            else:
                logger.info("[bg/%s] No new unique recipes to append", pool_id[:8])

    except Exception as exc:
        logger.error("[bg/%s] Background fetch failed: %s", pool_id[:8], exc, exc_info=True)


# ---------------------------------------------------------------------------
# Unlimited re-ideation — triggered when the pool runs low
# ---------------------------------------------------------------------------
async def _bg_full_refetch(
    pool_id: str,
    user_id: str,
    session_context_dict: dict,
    existing_ids: set[str],
    refetch_index: int,
) -> None:
    """
    Fire a brand-new LLM ideation round using the same session context.
    All previously fetched recipe IDs are excluded so only fresh recipes are added.
    """
    logger.info(
        "[bg-refetch/%s] Starting re-ideation #%d (excluding %d known recipes)",
        pool_id[:8], refetch_index, len(existing_ids),
    )
    try:
        from app.schemas import SessionContextRequest
        ctx = SessionContextRequest(**session_context_dict)

        async with db_session_factory() as db:
            # Load user prefs for cuisine/equipment/dietary
            from app.models import UserPreferences, CookHistory, SavedRecipe
            prefs_result = await db.execute(
                select(UserPreferences).where(UserPreferences.user_id == user_id)
            )
            prefs = prefs_result.scalar_one_or_none()
            dietary = list(prefs.dietary_restrictions or []) if prefs else []
            cuisines = list(prefs.cuisine_preferences or []) if prefs else []
            equipment = list(prefs.cooking_equipment or []) if prefs else []
            health_goal = (prefs.health_goal or "none") if prefs else "none"

            # Get current shown recipe titles to avoid repeating them
            pool_result = await db.execute(
                select(SessionPool).where(SessionPool.id == pool_id)
            )
            pool = pool_result.scalar_one_or_none()
            if not pool:
                logger.warning("[bg-refetch/%s] Pool not found — aborting", pool_id[:8])
                return

            current_ids = {r["recipeId"] for r in (pool.recipes or [])}
            all_excluded = existing_ids | current_ids

            # Get titles of all already-fetched recipes so LLM avoids suggesting them
            if all_excluded:
                cache_result = await db.execute(
                    select(RecipeCache.title).where(RecipeCache.id.in_(all_excluded))
                )
                shown_titles = [row[0] for row in cache_result.all()]
            else:
                shown_titles = []

            logger.info(
                "[bg-refetch/%s] Excluding %d shown titles from new ideation",
                pool_id[:8], len(shown_titles),
            )

            # New ideation round — LLM will avoid previously seen recipes via history
            new_suggestions = await llm_service.ideate_recipes(
                context=ctx,
                dietary_restrictions=dietary,
                cuisine_preferences=cuisines,
                health_goal=health_goal,
                history_titles=shown_titles,
                cooking_equipment=equipment,
            )

            if not new_suggestions:
                logger.warning("[bg-refetch/%s] Re-ideation produced 0 suggestions", pool_id[:8])
                return

            # Fetch recipes for new suggestions
            new_recipes_raw = await recipe_fetcher.fetch_recipes_batch(new_suggestions, ctx, db)

            if not new_recipes_raw:
                logger.info("[bg-refetch/%s] Re-fetch resolved 0 recipes", pool_id[:8])
                return

            # Rank
            ranked = await ranking_service.rank_recipes(
                recipes=new_recipes_raw,
                context=ctx,
                dietary_restrictions=dietary,
                cuisine_preferences=cuisines,
                cooking_equipment=equipment,
                mode=RANKING_MODE,
            )

            # Reload pool (may have changed during fetch)
            pool_result2 = await db.execute(
                select(SessionPool).where(SessionPool.id == pool_id)
            )
            pool = pool_result2.scalar_one_or_none()
            if not pool:
                return

            current_pool = list(pool.recipes or [])
            current_ids2 = {r["recipeId"] for r in current_pool}
            new_entries = []
            for r in ranked:
                if r["id"] in current_ids2 or r["id"] in all_excluded:
                    continue
                current_ids2.add(r["id"])
                new_entries.append({
                    "recipeId": r["id"],
                    "score": r.get("score", 0.0),
                    "status": "unshown",
                    "shownAt": None,
                    "rankPosition": len(current_pool) + len(new_entries) + 1,
                })
                cached = RecipeCache(
                    id=r["id"], title=r["title"],
                    description=r.get("description", ""), image=r.get("image", ""),
                    prep_time=r.get("prep_time", 10), cook_time=r.get("cook_time", 25),
                    total_time=r.get("total_time", 35), difficulty=r.get("difficulty", "medium"),
                    servings=r.get("servings", 4), cuisine=r.get("cuisine", ""),
                    meal_type=r.get("meal_type", []), occasions=r.get("occasions", []),
                    rating=r.get("rating", 4.0), source=r.get("source", "web"),
                    source_url=r.get("source_url", ""),
                    cooking_equipment=r.get("cooking_equipment", []),
                    ingredients=r.get("ingredients", []),
                    instructions=r.get("instructions", []),
                )
                await db.merge(cached)

            if new_entries:
                pool.recipes = current_pool + new_entries
                pool.total_fetched = (pool.total_fetched or 0) + len(new_entries)
                flag_modified(pool, "recipes")
                await db.commit()
                logger.info(
                    "[bg-refetch/%s] Re-ideation #%d appended %d fresh recipes (pool total=%d)",
                    pool_id[:8], refetch_index, len(new_entries), pool.total_fetched,
                )
            else:
                logger.info("[bg-refetch/%s] Re-ideation #%d: no new unique recipes", pool_id[:8], refetch_index)

    except Exception as exc:
        logger.error("[bg-refetch/%s] Re-ideation failed: %s", pool_id[:8], exc, exc_info=True)


async def get_next_batch(pool: SessionPool, db: AsyncSession) -> NextBatchResponse:
    pool_recipes = pool.recipes or []
    unshown = [r for r in pool_recipes if r["status"] == "unshown"]
    batch_ids = [r["recipeId"] for r in unshown[:BATCH_SIZE]]

    # Guard: if nothing unshown yet (background fetch still in progress),
    # return empty rather than issuing an invalid SQL IN () query.
    if not batch_ids:
        return NextBatchResponse(
            recipes=[],
            shown_count=pool.shown_count or 0,
            pool_size=pool.total_fetched or 0,
            refetch_triggered=False,
        )

    now = datetime.now(timezone.utc).isoformat()
    for pr in pool_recipes:
        if pr["recipeId"] in batch_ids:
            pr["status"] = "shown"
            pr["shownAt"] = now
    pool.shown_count = (pool.shown_count or 0) + len(batch_ids)
    pool.recipes = pool_recipes
    flag_modified(pool, "recipes")

    result = await db.execute(
        select(RecipeCache).where(RecipeCache.id.in_(batch_ids))
    )
    cached = {rc.id: rc for rc in result.scalars().all()}
    recipes_out = [
        _to_out(_recipe_cache_to_dict(cached[rid]))
        for rid in batch_ids
        if rid in cached
    ]

    # Trigger unlimited re-ideation when pool is nearly empty
    # (after current batch is served, fewer than BATCH_SIZE unshown remain)
    remaining_unshown = len(unshown) - len(batch_ids)
    MAX_REFETCHES = 20  # hard cap to avoid runaway
    if (
        remaining_unshown < BATCH_SIZE
        and pool.session_context
        and (pool.refetch_count or 0) < MAX_REFETCHES
    ):
        pool.refetch_count = (pool.refetch_count or 0) + 1
        flag_modified(pool, "refetch_count")
        all_recipe_ids = {r["recipeId"] for r in pool_recipes}
        asyncio.create_task(
            _bg_full_refetch(
                pool_id=pool.id,
                user_id=pool.user_id,
                session_context_dict=pool.session_context,
                existing_ids=all_recipe_ids,
                refetch_index=pool.refetch_count,
            )
        )
        logger.info(
            "[%s] Pool running low (%d unshown) — firing re-ideation #%d in background",
            pool.id[:8], remaining_unshown, pool.refetch_count,
        )

    shown_since_save = sum(1 for r in pool_recipes if r["status"] == "shown")
    refetch = shown_since_save >= 10 and (pool.saved_count or 0) == 0

    await db.commit()

    return NextBatchResponse(
        recipes=recipes_out,
        shown_count=pool.shown_count,
        pool_size=pool.total_fetched or 0,
        refetch_triggered=refetch,
    )


async def rerank_pool(
    pool: SessionPool,
    liked_recipe_id: str,
    action: str,
    db: AsyncSession,
) -> RerankResponse:
    pool_recipes = pool.recipes or []
    for pr in pool_recipes:
        if pr["recipeId"] == liked_recipe_id:
            pr["status"] = "saved"
    pool.saved_count = (pool.saved_count or 0) + 1
    pool.last_preference_inference = f"User {action}d {liked_recipe_id}"
    pool.recipes = pool_recipes
    flag_modified(pool, "recipes")
    pool.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return RerankResponse(
        message="Pool updated with preference signal",
        preference_inference=pool.last_preference_inference,
    )


def _recipe_cache_to_dict(rc: RecipeCache) -> dict:
    return {
        "id": rc.id,
        "title": rc.title,
        "description": rc.description,
        "image": rc.image,
        "prep_time": rc.prep_time,
        "cook_time": rc.cook_time,
        "total_time": rc.total_time,
        "difficulty": rc.difficulty,
        "servings": rc.servings,
        "cuisine": rc.cuisine,
        "meal_type": rc.meal_type,
        "occasions": rc.occasions,
        "rating": rc.rating,
        "source": rc.source,
        "source_url": rc.source_url,
        "cooking_equipment": rc.cooking_equipment,
        "ingredients": rc.ingredients,
        "instructions": rc.instructions,
        "score": 0.0,
    }


def _to_out(r: dict) -> RecipeOut:
    return RecipeOut(
        id=r["id"],
        title=r["title"],
        description=r.get("description", ""),
        image=r.get("image", ""),
        prep_time=r.get("prep_time", 10),
        cook_time=r.get("cook_time", 25),
        total_time=r.get("total_time", 35),
        difficulty=r.get("difficulty", "medium"),
        servings=r.get("servings", 4),
        cuisine=r.get("cuisine", ""),
        meal_type=r.get("meal_type", []),
        occasions=r.get("occasions", []),
        rating=r.get("rating", 4.0),
        source_url=r.get("source_url", ""),
        cooking_equipment=r.get("cooking_equipment", []),
        ingredients=r.get("ingredients", []),
        instructions=r.get("instructions", []),
        score=r.get("score", 0.0),
    )
