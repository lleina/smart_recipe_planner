"""
Spoonacular API client — cache-first recipe fetcher.

Strategy:
  1. For each LLM suggestion, attempt a token-overlap title match against
     recipes already in RecipeCache (free — 0 credits).
  2. Only call the Spoonacular API on a genuine cache miss.
  3. Every API result is immediately upserted to RecipeCache so the same
     recipe is never fetched twice.

Credit cost logging:
  Every live API call logs an estimated credit cost and a running session
  total, so it is always visible how many credits are being consumed.

Usage:
  from app.services.spoonacular_client import find_recipe, get_credits_used
"""

import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SPOONACULAR_API_KEY, SPOONACULAR_BASE_URL
from app.models import RecipeCache

logger = logging.getLogger("app.spoonacular")

# Running tally for this process lifetime (resets on server restart).
# This is intentionally approximate — use Spoonacular's own dashboard for
# authoritative credit usage.
_credits_used_this_session: int = 0

# Words ignored when comparing recipe titles for cache lookup.
_STOP_WORDS = {"with", "and", "in", "on", "of", "the", "a", "an", "for", "or"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def find_recipe(
    suggestion_name: str,
    key_ingredients: list[str],
    db: AsyncSession,
    cuisine_preferences: list[str] | None = None,
    diet: str | None = None,
    intolerances: list[str] | None = None,
    equipment: list[str] | None = None,
    min_cache_score: float = 0.5,
) -> dict | None:
    """
    Returns a recipe dict for the given suggestion name.

    Cache hit  → 0 credits, fast.
    Cache miss → 1 Spoonacular API call (~2 credits), result stored in cache.
    Returns None if nothing found anywhere.
    """
    cached = await _search_cache(suggestion_name, db, min_cache_score)
    if cached:
        logger.debug("Cache HIT: '%s' → '%s'", suggestion_name, cached["title"])
        return cached

    logger.info("[SPOONACULAR] Cache MISS for '%s' — calling API", suggestion_name)
    return await _call_api(
        suggestion_name, key_ingredients, db,
        cuisine_preferences=cuisine_preferences,
        diet=diet,
        intolerances=intolerances,
        equipment=equipment,
    )


def get_credits_used() -> int:
    """Returns the approximate number of Spoonacular credits spent this session."""
    return _credits_used_this_session


# ---------------------------------------------------------------------------
# Cache lookup
# ---------------------------------------------------------------------------

def _title_tokens(title: str) -> set[str]:
    """Lowercased, punctuation-stripped, de-stopworded title tokens."""
    words = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _title_match_score(cache_title: str, query: str) -> float:
    """
    Fraction of query tokens that appear in the cache title.
    e.g. query='Honey Garlic Chicken', cache='Honey Garlic Chicken Stir Fry' → 1.0
         query='Korean Bibimbap', cache='Beef Bibimbap Bowl'                  → 0.33
    """
    q_tokens = _title_tokens(query)
    c_tokens = _title_tokens(cache_title)
    if not q_tokens:
        return 0.0
    return len(q_tokens & c_tokens) / len(q_tokens)


async def _search_cache(
    name: str,
    db: AsyncSession,
    min_score: float,
) -> dict | None:
    result = await db.execute(select(RecipeCache))
    rows = result.scalars().all()

    best_score = 0.0
    best_row: RecipeCache | None = None
    for row in rows:
        score = _title_match_score(row.title, name)
        if score > best_score:
            best_score = score
            best_row = row

    if best_score >= min_score and best_row is not None:
        return _cache_row_to_dict(best_row)
    return None


# ---------------------------------------------------------------------------
# Live API call
# ---------------------------------------------------------------------------

# Intolerance → ingredient keywords used to build excludeIngredients
_INTOLERANCE_EXCLUDE: dict[str, str] = {
    "dairy": "milk,butter,cream,cheese,yogurt,whey,lactose",
    "egg": "eggs,egg yolk,egg white",
    "gluten": "gluten,barley,rye,spelt",
    "grain": "wheat,barley,rye,oats,corn flour,buckwheat",
    "peanut": "peanuts,peanut butter,peanut oil",
    "seafood": "fish,salmon,tuna,cod,tilapia,halibut,sardine,anchovy",
    "sesame": "sesame,tahini,sesame oil,sesame seeds",
    "shellfish": "shrimp,crab,lobster,scallops,mussels,clams,oysters",
    "soy": "soy,tofu,edamame,soy sauce,tempeh,miso,soybean",
    "sulfite": "wine,dried fruit,vinegar,beer",
    "tree nut": "almonds,walnuts,cashews,pecans,pistachios,hazelnuts,macadamia nuts",
    "wheat": "wheat,wheat flour,bread flour,semolina,spelt,durum",
}


async def _call_api(
    query: str,
    key_ingredients: list[str],
    db: AsyncSession,
    cuisine_preferences: list[str] | None = None,
    diet: str | None = None,
    intolerances: list[str] | None = None,
    equipment: list[str] | None = None,
) -> dict | None:
    global _credits_used_this_session

    if not SPOONACULAR_API_KEY:
        logger.warning("[SPOONACULAR] No API key — cannot fetch '%s'", query)
        return None

    params: dict = {
        "apiKey": SPOONACULAR_API_KEY,
        "query": query,
        "number": 1,
        "addRecipeInformation": "true",
        "fillIngredients": "true",
        "instructionsRequired": "true",
    }
    if key_ingredients:
        params["includeIngredients"] = ",".join(key_ingredients[:5])
    if cuisine_preferences:
        params["cuisine"] = ",".join(cuisine_preferences)
    if diet:
        params["diet"] = diet
    if intolerances:
        params["intolerances"] = ",".join(intolerances)
        # Belt-and-suspenders: also exclude likely allergen ingredients
        exclude_parts = [
            _INTOLERANCE_EXCLUDE[i] for i in intolerances if i in _INTOLERANCE_EXCLUDE
        ]
        if exclude_parts:
            params["excludeIngredients"] = ",".join(exclude_parts)
    if equipment:
        params["equipment"] = ",".join(equipment)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SPOONACULAR_BASE_URL}/recipes/complexSearch", params=params
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    if not results:
        logger.warning("[SPOONACULAR] No results from API for '%s'", query)
        return None

    raw = results[0]
    # complexSearch with addRecipeInformation costs roughly 2 points per result
    estimated_cost = len(results) * 2
    _credits_used_this_session += estimated_cost
    logger.info(
        "[SPOONACULAR] Fetched '%s' → '%s' | est. cost: ~%d credits | "
        "session total: ~%d credits",
        query,
        raw.get("title", "?"),
        estimated_cost,
        _credits_used_this_session,
    )

    recipe_dict = _spoonacular_to_dict(raw)

    # Upsert to cache — auto-deduplicates by spoonacular_id
    cached = RecipeCache(
        id=f"sp-{raw['id']}",
        spoonacular_id=str(raw["id"]),
        title=recipe_dict["title"],
        description=recipe_dict.get("description", ""),
        image=recipe_dict.get("image", ""),
        prep_time=recipe_dict.get("prep_time", 0),
        cook_time=recipe_dict.get("cook_time", 0),
        total_time=recipe_dict.get("total_time", 0),
        difficulty=recipe_dict.get("difficulty", "medium"),
        servings=recipe_dict.get("servings", 4),
        cuisine=recipe_dict.get("cuisine", ""),
        meal_type=recipe_dict.get("meal_type", []),
        occasions=recipe_dict.get("occasions", []),
        rating=recipe_dict.get("rating", 0.0),
        source="spoonacular",
        source_url=recipe_dict.get("source_url", ""),
        cooking_equipment=[],
        ingredients=recipe_dict.get("ingredients", []),
        instructions=recipe_dict.get("instructions", []),
    )
    await db.merge(cached)
    await db.commit()

    return recipe_dict


# ---------------------------------------------------------------------------
# Data mapping helpers
# ---------------------------------------------------------------------------

def _spoonacular_to_dict(raw: dict) -> dict:
    """Convert a Spoonacular complexSearch result (addRecipeInformation=true) to pipeline dict."""
    cuisines: list = raw.get("cuisines") or []
    dish_types: list = raw.get("dishTypes") or []

    prep = int(raw.get("preparationMinutes") or 0)
    cook = int(raw.get("cookingMinutes") or 0)
    total = int(raw.get("readyInMinutes") or 0)
    # Spoonacular sometimes only populates readyInMinutes
    if not prep and not cook and total:
        prep = max(5, total // 3)
        cook = total - prep
    elif not total:
        total = prep + cook or 35

    ingredients = [
        {
            "name": (i.get("nameClean") or i.get("name") or "").lower().strip(),
            "quantity": round(float(i.get("amount") or 1), 2),
            "unit": i.get("unit") or "piece",
        }
        for i in (raw.get("extendedIngredients") or [])
        if (i.get("nameClean") or i.get("name"))
    ]

    instructions = []
    for block in raw.get("analyzedInstructions") or []:
        for step in block.get("steps") or []:
            instructions.append({
                "step": step.get("number", len(instructions) + 1),
                "text": step.get("step", ""),
                "image": None,
            })
    if not instructions:
        instructions = [
            {"step": 1, "text": "Prepare all ingredients.", "image": None},
            {"step": 2, "text": "Cook according to method.", "image": None},
            {"step": 3, "text": "Season to taste and serve.", "image": None},
        ]

    # Map Spoonacular 0–100 score to our 0.0–5.0 rating
    sp_score = float(raw.get("spoonacularScore") or 0.0)
    rating = round((sp_score / 100.0) * 5.0, 1)

    summary = raw.get("summary") or ""
    # Strip HTML tags from summary
    description = re.sub(r"<[^>]+>", "", summary)[:500]

    return {
        "id": f"sp-{raw['id']}",
        "spoonacular_id": str(raw["id"]),
        "title": raw.get("title", "Unknown Recipe"),
        "description": description,
        "image": raw.get("image", ""),
        "prep_time": prep,
        "cook_time": cook,
        "total_time": total,
        "difficulty": _estimate_difficulty(total, len(instructions)),
        "servings": int(raw.get("servings") or 4),
        "cuisine": cuisines[0].lower() if cuisines else "",
        "meal_type": [dt.lower() for dt in dish_types],
        "occasions": [o.lower() for o in (raw.get("occasions") or [])],
        "rating": rating,
        "source_url": raw.get("sourceUrl", ""),
        "cooking_equipment": [],
        "ingredients": ingredients,
        "instructions": instructions,
        "dietary_tags": _extract_dietary_tags(raw),
        "score": 0.0,
    }


def _estimate_difficulty(total_time: int, instruction_count: int) -> str:
    if total_time <= 20 or instruction_count <= 3:
        return "easy"
    if total_time <= 45 or instruction_count <= 7:
        return "medium"
    return "hard"


def _extract_dietary_tags(raw: dict) -> list[str]:
    tags = []
    if raw.get("vegan"):
        tags.append("vegan")
    if raw.get("vegetarian"):
        tags.append("vegetarian")
    if raw.get("glutenFree"):
        tags.append("gluten-free")
    if raw.get("dairyFree"):
        tags.append("dairy-free")
    return tags


def _cache_row_to_dict(row: RecipeCache) -> dict:
    return {
        "id": row.id,
        "spoonacular_id": row.spoonacular_id,
        "title": row.title,
        "description": row.description or "",
        "image": row.image or "",
        "prep_time": row.prep_time or 0,
        "cook_time": row.cook_time or 0,
        "total_time": row.total_time or 0,
        "difficulty": row.difficulty or "medium",
        "servings": row.servings or 4,
        "cuisine": row.cuisine or "",
        "meal_type": row.meal_type or [],
        "occasions": row.occasions or [],
        "rating": row.rating or 0.0,
        "source_url": row.source_url or "",
        "cooking_equipment": row.cooking_equipment or [],
        "ingredients": row.ingredients or [],
        "instructions": row.instructions or [],
        "dietary_tags": [],
        "score": 0.0,
    }
