"""
Recipe pipeline service - orchestrates LLM ideation, Spoonacular fetch, and ranking.

Stage flow:
  1. Context Assembly  - merge user prefs + session context (done by caller)
  2. LLM Ideation      - generate ~40 recipe name suggestions (llm_service)
  3. Recipe Fetch      - match suggestions to real recipes (mock -> Spoonacular later)
  4. Initial Ranking   - rule score + optional LLM re-rank (ranking_service)
  5. Serve             - first 5 to client, rest held in session_pool

Ranking mode is set by RecommendRequest.ranking_mode or falls back to
the RANKING_MODE environment variable (default: hybrid).
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.pipeline")
from app.models import SessionPool, RecipeCache, UserPreferences, CookHistory, SavedRecipe
from app.schemas import (
    SessionContextRequest, RecommendResponse, NextBatchResponse,
    RerankResponse, RecipeOut,
)
from app.services import llm_service, ranking_service, spoonacular_client
from app.config import RANKING_MODE, SPOONACULAR_API_KEY, USE_MOCK_RECIPES

BATCH_SIZE = 5


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
    Runs the full 5-stage recipe pipeline and returns the first batch.
    ranking_mode_override overrides the RANKING_MODE config for this request.
    """
    dietary_restrictions = list(preferences.dietary_restrictions or []) if preferences else []
    cuisine_preferences = list(preferences.cuisine_preferences or []) if preferences else []
    cooking_equipment = list(preferences.cooking_equipment or []) if preferences else []
    intolerances = list(preferences.intolerances or []) if preferences else []
    diet = (preferences.diet or None) if preferences else None
    health_goal = (preferences.health_goal or "none") if preferences else "none"
    history_titles = [h.recipe_id for h in history[:10]]

    # Stage 2: LLM ideation
    logger.info("[%s] Stage 2: LLM ideation (meal=%s, time=%dmin, ingredients=%d)",
                user_id[:8], session_context.meal_type,
                session_context.available_time_minutes,
                len(session_context.available_ingredients))
    suggestions = await llm_service.ideate_recipes(
        context=session_context,
        dietary_restrictions=dietary_restrictions,
        cuisine_preferences=cuisine_preferences,
        health_goal=health_goal,
        history_titles=history_titles,
    )

    # Stage 3: Recipe fetch (cache-first Spoonacular or mock fallback)
    logger.info(
        "[%s] Stage 3: fetching %d recipes (mode=%s)",
        user_id[:8], len(suggestions),
        "MOCK" if (USE_MOCK_RECIPES or not SPOONACULAR_API_KEY) else "SPOONACULAR",
    )
    recipes_raw = await _fetch_recipes(
        suggestions, session_context, db,
        cuisine_preferences=cuisine_preferences,
        diet=diet,
        intolerances=intolerances,
        cooking_equipment=cooking_equipment,
    )

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
        total_fetched=len(ranked),
        shown_count=0,
        saved_count=0,
        last_preference_inference=effective_mode,
    )
    db.add(pool)

    for r in ranked:
        cached = RecipeCache(
            id=r["id"],
            spoonacular_id=r.get("spoonacular_id", r["id"]),
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

    # Log the final ranked order so you can compare LLM suggestions → final cards
    credits = spoonacular_client.get_credits_used()
    if credits > 0:
        logger.info("[%s] Spoonacular credits used this session: ~%d", user_id[:8], credits)
    logger.info("[%s] Stage 4 → final ranking (%d recipes):", user_id[:8], len(ranked))
    for pos, r in enumerate(ranked, 1):
        score_str = f"{r.get('score', 0):.1f}"
        ingr_names = ", ".join(i.get("name", "") for i in (r.get("ingredients") or [])[:4])
        logger.info(
            "  %2d. %-45s | score=%s | cuisine=%-14s | ingredients: %s",
            pos, r.get("title", "?"), score_str, r.get("cuisine", ""), ingr_names,
        )

    logger.info("[%s] Stage 5: pool %s created — %d recipes, serving first %d",
                user_id[:8], pool_id[:8], len(ranked), min(BATCH_SIZE, len(ranked)))

    return RecommendResponse(
        session_pool_id=pool.id,
        recipes=[_to_out(r) for r in ranked[:BATCH_SIZE]],
        pool_size=len(ranked),
        shown_count=BATCH_SIZE,
        ranking_mode_used=effective_mode,
    )


async def get_next_batch(pool: SessionPool, db: AsyncSession) -> NextBatchResponse:
    pool_recipes = pool.recipes or []
    unshown = [r for r in pool_recipes if r["status"] == "unshown"]
    batch_ids = [r["recipeId"] for r in unshown[:BATCH_SIZE]]

    now = datetime.now(timezone.utc).isoformat()
    for pr in pool_recipes:
        if pr["recipeId"] in batch_ids:
            pr["status"] = "shown"
            pr["shownAt"] = now
    pool.shown_count = (pool.shown_count or 0) + len(batch_ids)
    pool.recipes = pool_recipes

    # Look up recipe details from the DB cache (populated by run_pipeline)
    result = await db.execute(
        select(RecipeCache).where(RecipeCache.id.in_(batch_ids))
    )
    cached = {rc.id: rc for rc in result.scalars().all()}
    recipes_out = [
        _to_out(_recipe_cache_to_dict(cached[rid]))
        for rid in batch_ids
        if rid in cached
    ]

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
    pool.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return RerankResponse(
        message="Pool re-ranked based on preference inference",
        preference_inference=pool.last_preference_inference,
    )


async def _fetch_recipes(
    suggestions: list[dict],
    ctx: SessionContextRequest,
    db: AsyncSession,
    cuisine_preferences: list[str] | None = None,
    diet: str | None = None,
    intolerances: list[str] | None = None,
    cooking_equipment: list[str] | None = None,
) -> list[dict]:
    """
    Stage 3 dispatch:
    - USE_MOCK_RECIPES=true (default) or no key → fast mock templates, 0 credits.
    - USE_MOCK_RECIPES=false + key present  → cache-first Spoonacular lookup.
    """
    if USE_MOCK_RECIPES or not SPOONACULAR_API_KEY:
        return _fetch_recipes_mock(suggestions, ctx)
    return await _fetch_recipes_spoonacular(
        suggestions, ctx, db,
        cuisine_preferences=cuisine_preferences,
        diet=diet,
        intolerances=intolerances,
        cooking_equipment=cooking_equipment,
    )


async def _fetch_recipes_spoonacular(
    suggestions: list[dict],
    ctx: SessionContextRequest,
    db: AsyncSession,
    cuisine_preferences: list[str] | None = None,
    diet: str | None = None,
    intolerances: list[str] | None = None,
    cooking_equipment: list[str] | None = None,
) -> list[dict]:
    """
    Cache-first Spoonacular fetch.
    For each LLM suggestion:
      1. Check RecipeCache by title similarity — free.
      2. On cache miss, call Spoonacular — costs ~2 credits.
    Suggestions that cannot be resolved are silently dropped.
    """
    results = []
    for suggestion in suggestions:
        try:
            recipe = await spoonacular_client.find_recipe(
                suggestion_name=suggestion.get("name", ""),
                key_ingredients=suggestion.get("key_ingredients", []),
                db=db,
                cuisine_preferences=cuisine_preferences,
                diet=diet,
                intolerances=intolerances,
                equipment=cooking_equipment,
            )
            if recipe:
                # Keep LLM time estimate; Spoonacular's can be inaccurate
                if suggestion.get("estimated_time"):
                    recipe["total_time"] = suggestion["estimated_time"]
                recipe["meal_type"] = [ctx.meal_type]
                results.append(recipe)
        except Exception as exc:
            logger.warning("Spoonacular lookup failed for '%s': %s", suggestion.get("name"), exc)
    logger.info(
        "Spoonacular fetch complete: %d/%d suggestions resolved",
        len(results), len(suggestions),
    )
    return results


def _fetch_recipes_mock(
    suggestions: list[dict],
    ctx: SessionContextRequest,
) -> list[dict]:
    """
    Mock recipe fetch: zero API calls, zero credits.
    Uses hardcoded templates as skeletons but substitutes the LLM's
    suggestion name, cuisine, time, and key_ingredients so the ranker
    scores against real pantry data rather than hardcoded mock ingredients.
    """
    result = []
    for i, suggestion in enumerate(suggestions):
        mock_idx = i % len(_MOCK_RECIPES)
        base = dict(_MOCK_RECIPES[mock_idx])
        base["id"] = f"r{i:02d}"
        base["spoonacular_id"] = f"sp-gen-{i:04d}"
        base["title"] = suggestion.get("name", base["title"])
        base["cuisine"] = suggestion.get("cuisine", base["cuisine"])
        base["total_time"] = suggestion.get("estimated_time", base["total_time"])
        base["meal_type"] = [ctx.meal_type]

        # --- KEY FIX: use the LLM's key_ingredients for scoring, not the mock
        # template's ingredients. Without this, the ranker compares mock salmon/
        # pasta/etc. against the user's actual pantry and produces nonsense scores.
        key_ingr = suggestion.get("key_ingredients", [])
        if key_ingr:
            base["ingredients"] = [
                {"name": name.lower().strip(), "quantity": 1, "unit": "as needed"}
                for name in key_ingr
            ]

        result.append(base)
    return result


def _recipe_cache_to_dict(rc: RecipeCache) -> dict:
    """
    Converts a RecipeCache ORM row to the dict shape expected by _to_out.
    """
    return {
        "id": rc.id,
        "spoonacular_id": rc.spoonacular_id,
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
        "source_url": rc.source_url,
        "cooking_equipment": rc.cooking_equipment,
        "ingredients": rc.ingredients,
        "instructions": rc.instructions,
        "score": 0.0,
    }


def _to_out(r: dict) -> RecipeOut:
    return RecipeOut(
        id=r["id"],
        spoonacular_id=r.get("spoonacular_id"),
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


_MOCK_RECIPES = [
    {
        "id": f"r{i:02d}",
        "spoonacular_id": f"sp-{1000+i}",
        "title": title,
        "description": desc,
        "image": f"https://spoonacular.com/recipeImages/{1000+i}-312x231.jpg",
        "prep_time": prep,
        "cook_time": cook,
        "total_time": prep + cook,
        "difficulty": diff,
        "servings": 4,
        "cuisine": cuisine,
        "meal_type": ["dinner"],
        "occasions": ["weeknight"],
        "rating": rating,
        "source_url": f"https://spoonacular.com/recipes/{1000+i}",
        "cooking_equipment": equip,
        "ingredients": ingr,
        "instructions": [
            {"step": 1, "text": "Prepare all ingredients.", "image": None},
            {"step": 2, "text": "Cook according to method.", "image": None},
            {"step": 3, "text": "Season to taste and serve.", "image": None},
        ],
        "score": round(0.95 - i * 0.02, 2),
    }
    for i, (title, desc, prep, cook, diff, cuisine, rating, equip, ingr) in enumerate([
        ("Tomato Basil Pasta", "Classic Italian pasta with fresh tomatoes and basil",
         10, 20, "easy", "italian", 4.7, ["stovetop"],
         [{"name": "pasta", "quantity": 1, "unit": "lb"}, {"name": "tomato", "quantity": 4, "unit": "pieces"}]),
        ("Chicken Stir Fry", "Quick and healthy chicken with mixed vegetables",
         15, 15, "easy", "asian", 4.5, ["stovetop", "wok"],
         [{"name": "chicken breast", "quantity": 2, "unit": "pieces"}, {"name": "bell pepper", "quantity": 2, "unit": "pieces"}]),
        ("Grilled Salmon Bowl", "Fresh salmon over rice with avocado and greens",
         10, 15, "medium", "japanese", 4.8, ["grill", "stovetop"],
         [{"name": "salmon fillet", "quantity": 2, "unit": "pieces"}, {"name": "rice", "quantity": 1, "unit": "cups"}]),
        ("Vegetable Curry", "Creamy coconut curry with seasonal vegetables",
         15, 25, "medium", "indian", 4.6, ["stovetop"],
         [{"name": "coconut milk", "quantity": 1, "unit": "can"}, {"name": "onion", "quantity": 2, "unit": "pieces"}]),
        ("Mediterranean Quinoa Salad", "Light and refreshing quinoa with olives and feta",
         15, 15, "easy", "mediterranean", 4.4, ["stovetop"],
         [{"name": "quinoa", "quantity": 1, "unit": "cups"}, {"name": "tomato", "quantity": 3, "unit": "pieces"}]),
        ("Beef Tacos", "Seasoned ground beef tacos with fresh toppings",
         10, 15, "easy", "mexican", 4.5, ["stovetop"],
         [{"name": "ground beef", "quantity": 1, "unit": "lb"}, {"name": "onion", "quantity": 1, "unit": "pieces"}]),
        ("Mushroom Risotto", "Creamy arborio rice with mixed mushrooms",
         10, 30, "medium", "italian", 4.7, ["stovetop"],
         [{"name": "arborio rice", "quantity": 1, "unit": "cups"}, {"name": "mushroom", "quantity": 8, "unit": "pieces"}]),
        ("Thai Green Curry", "Spicy green curry with chicken and Thai basil",
         15, 20, "medium", "thai", 4.6, ["stovetop"],
         [{"name": "chicken thigh", "quantity": 1, "unit": "lb"}, {"name": "green curry paste", "quantity": 2, "unit": "tbsp"}]),
        ("Sheet Pan Roasted Vegetables", "Simple roasted seasonal vegetables with herbs",
         10, 25, "easy", "american", 4.3, ["oven"],
         [{"name": "bell pepper", "quantity": 2, "unit": "pieces"}, {"name": "zucchini", "quantity": 2, "unit": "pieces"}]),
        ("Lemon Herb Chicken", "Juicy oven-roasted chicken with lemon and herbs",
         10, 35, "easy", "american", 4.6, ["oven"],
         [{"name": "chicken breast", "quantity": 4, "unit": "pieces"}, {"name": "lemon", "quantity": 2, "unit": "pieces"}]),
    ])
]
