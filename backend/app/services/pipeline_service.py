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
INITIAL_FETCH_SIZE = 15
# Trigger a background re-ideation round when fewer than this many unshown
# recipes remain in the pool. Set to 3× BATCH_SIZE so the user always has at
# least two full pages buffered before we kick off new LLM ideation.
RE_IDEATION_TRIGGER_THRESHOLD = 15
# Hard cap on re-ideation rounds per session to prevent runaway AI calls.
MAX_REFETCH_ROUNDS = 20

# ---------------------------------------------------------------------------
# In-memory pipeline status — lets the generating screen show real progress.
# Keyed by user_id (one pipeline per user at a time).
# ---------------------------------------------------------------------------
_user_pipeline_status: dict[str, dict] = {}


def _set_status(user_id: str, step: int, label: str, detail: str = "") -> None:
    """Update the pipeline status for a user."""
    _user_pipeline_status[user_id] = {
        "step": step,
        "label": label,
        "detail": detail,
        "total_steps": 4,
    }


def get_pipeline_status(user_id: str) -> dict:
    """Return the current pipeline stage for a user (for polling endpoint)."""
    return _user_pipeline_status.get(user_id, {
        "step": 0, "label": "Starting up…", "detail": "", "total_steps": 4,
    })


def clear_pipeline_status(user_id: str) -> None:
    _user_pipeline_status.pop(user_id, None)


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

    # Clear any previous status and start fresh
    clear_pipeline_status(user_id)

    # Stage 2: LLM ideation
    _set_status(user_id, 1, "Brainstorming recipe ideas",
                f"{len(session_context.available_ingredients)} ingredient(s) · {session_context.meal_type}")
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
    _set_status(user_id, 2, "Searching the web for recipes",
                f"Looking up {len(first_suggestions)} recipe ideas…")
    logger.info(
        "[%s] Stage 3a: fast fetch — %d suggestions (remaining %d deferred to background)",
        user_id[:8], len(first_suggestions), len(rest_suggestions),
    )

    def _fetch_progress(done: int, total: int) -> None:
        _set_status(user_id, 2, "Searching the web for recipes",
                    f"Found {done} of {total} recipes")

    recipes_raw = await recipe_fetcher.fetch_recipes_batch(
        first_suggestions, session_context, db, progress_cb=_fetch_progress
    )

    # Stage 4: Ranking
    effective_mode = ranking_mode_override or RANKING_MODE
    _set_status(user_id, 3, "Ranking the best matches",
                f"Scoring {len(recipes_raw)} recipes for you")
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
            prep_time=r.get("prep_time", 0),
            cook_time=r.get("cook_time", 0),
            total_time=r.get("total_time", 0),
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
    # Report pool_size including expected background additions so the
    # frontend knows more recipes are on the way and keeps "Next" enabled.
    expected_total = len(ranked) + len(rest_suggestions)
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

    _set_status(user_id, 4, "Recipes ready!", f"Found {min(BATCH_SIZE, len(ranked))} great matches")
    return RecommendResponse(
        session_pool_id=pool.id,
        recipes=[_to_out(r) for r in ranked[:BATCH_SIZE]],
        pool_size=expected_total,
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
                    prep_time=r.get("prep_time", 0),
                    cook_time=r.get("cook_time", 0),
                    total_time=r.get("total_time", 0),
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
    refetch_index: int,
) -> None:
    """Run a new LLM ideation round and append fresh recipes to the session pool.

    Called automatically when the pool runs low on unshown recipes. Uses its
    own DB session because the originating request session has already closed.

    Previously seen recipe IDs are sourced **exclusively from a fresh DB query**
    at execution time rather than from a snapshot captured at trigger time.
    This is critical for correctness: multiple concurrent re-ideation rounds
    could otherwise each use a stale snapshot and produce overlapping results.

    Args:
        pool_id: The session pool to append fresh recipes to.
        user_id: Owner's user ID — used to load current preferences.
        session_context_dict: Serialized ``SessionContextRequest`` (stored on
            the pool row) used to reconstruct the original session context.
        refetch_index: Which re-ideation round this is (1-based); used in logs.
    """
    logger.info(
        "[bg-refetch/%s] Starting re-ideation round #%d",
        pool_id[:8], refetch_index,
    )
    try:
        session_context = SessionContextRequest(**session_context_dict)

        async with db_session_factory() as db:
            user_prefs_result = await db.execute(
                select(UserPreferences).where(UserPreferences.user_id == user_id)
            )
            user_prefs = user_prefs_result.scalar_one_or_none()
            dietary_restrictions = list(user_prefs.dietary_restrictions or []) if user_prefs else []
            cuisine_preferences = list(user_prefs.cuisine_preferences or []) if user_prefs else []
            cooking_equipment = list(user_prefs.cooking_equipment or []) if user_prefs else []
            health_goal = (user_prefs.health_goal or "none") if user_prefs else "none"

            # Fresh pool query — captures every recipe added since the trigger fired,
            # including those from concurrent re-ideation rounds.
            pool_result = await db.execute(
                select(SessionPool).where(SessionPool.id == pool_id)
            )
            session_pool = pool_result.scalar_one_or_none()
            if not session_pool:
                logger.warning("[bg-refetch/%s] Pool not found — aborting", pool_id[:8])
                return

            already_seen_ids = {
                recipe_slot["recipeId"]
                for recipe_slot in (session_pool.recipes or [])
            }

            # Fetch titles for the exclusion list so the LLM doesn't suggest recipes
            # the user has already seen in this session.
            if already_seen_ids:
                titles_result = await db.execute(
                    select(RecipeCache.title).where(RecipeCache.id.in_(already_seen_ids))
                )
                already_seen_titles = [row[0] for row in titles_result.all()]
            else:
                already_seen_titles = []

            logger.info(
                "[bg-refetch/%s] Excluding %d already-seen titles from ideation",
                pool_id[:8], len(already_seen_titles),
            )

            new_suggestions = await llm_service.ideate_recipes(
                context=session_context,
                dietary_restrictions=dietary_restrictions,
                cuisine_preferences=cuisine_preferences,
                health_goal=health_goal,
                history_titles=already_seen_titles,
                cooking_equipment=cooking_equipment,
            )

            if not new_suggestions:
                logger.warning("[bg-refetch/%s] Re-ideation produced 0 suggestions", pool_id[:8])
                return

            new_recipes_raw = await recipe_fetcher.fetch_recipes_batch(
                new_suggestions, session_context, db
            )
            if not new_recipes_raw:
                logger.info("[bg-refetch/%s] Web fetch resolved 0 recipes", pool_id[:8])
                return

            ranked_new_recipes = await ranking_service.rank_recipes(
                recipes=new_recipes_raw,
                context=session_context,
                dietary_restrictions=dietary_restrictions,
                cuisine_preferences=cuisine_preferences,
                cooking_equipment=cooking_equipment,
                mode=RANKING_MODE,
            )

            # Re-query pool to pick up any changes made while we were fetching.
            fresh_pool_result = await db.execute(
                select(SessionPool).where(SessionPool.id == pool_id)
            )
            session_pool = fresh_pool_result.scalar_one_or_none()
            if not session_pool:
                return

            current_pool_slots = list(session_pool.recipes or [])
            # Rebuild seen-ID set from latest pool state to prevent duplicates
            # across concurrent re-ideation rounds.
            current_pool_ids = {slot["recipeId"] for slot in current_pool_slots}

            new_pool_slots: list[dict] = []
            for ranked_recipe in ranked_new_recipes:
                if ranked_recipe["id"] in current_pool_ids:
                    continue
                current_pool_ids.add(ranked_recipe["id"])
                new_pool_slots.append({
                    "recipeId": ranked_recipe["id"],
                    "score": ranked_recipe.get("score", 0.0),
                    "status": "unshown",
                    "shownAt": None,
                    "rankPosition": len(current_pool_slots) + len(new_pool_slots) + 1,
                })
                await db.merge(RecipeCache(
                    id=ranked_recipe["id"],
                    title=ranked_recipe["title"],
                    description=ranked_recipe.get("description", ""),
                    image=ranked_recipe.get("image", ""),
                    prep_time=ranked_recipe.get("prep_time", 0),
                    cook_time=ranked_recipe.get("cook_time", 0),
                    total_time=ranked_recipe.get("total_time", 0),
                    difficulty=ranked_recipe.get("difficulty", "medium"),
                    servings=ranked_recipe.get("servings", 4),
                    cuisine=ranked_recipe.get("cuisine", ""),
                    meal_type=ranked_recipe.get("meal_type", []),
                    occasions=ranked_recipe.get("occasions", []),
                    rating=ranked_recipe.get("rating", 4.0),
                    source=ranked_recipe.get("source", "web"),
                    source_url=ranked_recipe.get("source_url", ""),
                    cooking_equipment=ranked_recipe.get("cooking_equipment", []),
                    ingredients=ranked_recipe.get("ingredients", []),
                    instructions=ranked_recipe.get("instructions", []),
                ))

            if new_pool_slots:
                session_pool.recipes = current_pool_slots + new_pool_slots
                session_pool.total_fetched = (session_pool.total_fetched or 0) + len(new_pool_slots)
                flag_modified(session_pool, "recipes")
                await db.commit()
                logger.info(
                    "[bg-refetch/%s] Round #%d appended %d fresh recipes (pool total=%d)",
                    pool_id[:8], refetch_index, len(new_pool_slots), session_pool.total_fetched,
                )
            else:
                logger.info(
                    "[bg-refetch/%s] Round #%d: all ranked recipes were already in pool",
                    pool_id[:8], refetch_index,
                )

    except Exception as exc:  # pylint: disable=broad-except
        # Top-level background task boundary — must not propagate.
        logger.error(
            "[bg-refetch/%s] Re-ideation round #%d failed: %s",
            pool_id[:8], refetch_index, exc, exc_info=True,
        )


async def get_next_batch(pool: SessionPool, db: AsyncSession) -> NextBatchResponse:
    pool_recipes = pool.recipes or []
    unshown = [r for r in pool_recipes if r["status"] == "unshown"]
    batch_ids = [r["recipeId"] for r in unshown[:BATCH_SIZE]]

    # Guard: if nothing unshown yet (background fetch still in progress),
    # return empty rather than issuing an invalid SQL IN () query.
    # Report pool_size as total pool entries (including unshown) so the
    # frontend knows more data may still arrive.
    if not batch_ids:
        effective_pool_size = max(pool.total_fetched or 0, len(pool_recipes))
        return NextBatchResponse(
            recipes=[],
            shown_count=pool.shown_count or 0,
            pool_size=effective_pool_size,
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

    # Recompute ingredient match info so later pages show the same stats as page 1
    session_ctx = None
    if pool.session_context:
        try:
            session_ctx = SessionContextRequest(**pool.session_context)
        except Exception:
            pass
    available_tokens = None
    if session_ctx:
        from app.services.ranking_service import compute_ingredient_match, _build_available_token_set
        available_tokens = _build_available_token_set(session_ctx.available_ingredients)

    recipes_out = []
    for rid in batch_ids:
        if rid not in cached:
            continue
        rdict = _recipe_cache_to_dict(cached[rid])
        if session_ctx and available_tokens is not None:
            match_info = compute_ingredient_match(rdict, session_ctx, available_tokens)
            rdict.update(match_info)
        recipes_out.append(_to_out(rdict))

    # Trigger a re-ideation round when the pool is running low.
    # Using RE_IDEATION_TRIGGER_THRESHOLD (15) instead of BATCH_SIZE (5) ensures
    # we start fetching new recipes early enough that the user never stalls.
    # _bg_full_refetch always re-queries the pool from the DB at execution time,
    # so we do not need to capture the current ID set here — it would be stale
    # by the time the background task runs, especially across concurrent rounds.
    remaining_unshown = len(unshown) - len(batch_ids)
    if (
        remaining_unshown < RE_IDEATION_TRIGGER_THRESHOLD
        and pool.session_context
        and (pool.refetch_count or 0) < MAX_REFETCH_ROUNDS
    ):
        pool.refetch_count = (pool.refetch_count or 0) + 1
        flag_modified(pool, "refetch_count")
        asyncio.create_task(
            _bg_full_refetch(
                pool_id=pool.id,
                user_id=pool.user_id,
                session_context_dict=pool.session_context,
                refetch_index=pool.refetch_count,
            )
        )
        logger.info(
            "[%s] Pool running low (%d unshown < threshold %d) — firing re-ideation #%d",
            pool.id[:8], remaining_unshown, RE_IDEATION_TRIGGER_THRESHOLD, pool.refetch_count,
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
        prep_time=r.get("prep_time", 0),
        cook_time=r.get("cook_time", 0),
        total_time=r.get("total_time", 0),
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
        ingredient_match_pct=r.get("ingredient_match_pct", 0.0),
        matched_ingredient_count=r.get("matched_ingredient_count", 0),
        total_ingredient_count=r.get("total_ingredient_count", 0),
        missing_key_ingredients=r.get("missing_key_ingredients", []),
        swap_suggestions=r.get("swap_suggestions", []),
    )
