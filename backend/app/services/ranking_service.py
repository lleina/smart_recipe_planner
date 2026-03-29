"""
Ranking service - scores and re-ranks candidate recipes against user context.

Three modes (set via RANKING_MODE config or per-request override):
  rules_only  - fast deterministic scoring only; no LLM call
  llm_only    - pass all candidates directly to LLM for ranking
  hybrid      - rules first (hard filter + rough rank), top 15 to LLM re-ranker

The mode can be overridden per-request via the ranking_mode field in
RecommendRequest, enabling A/B comparison between modes.

Rule scorer weights:
  time fit:           25 pts  (hard filter if > +15 min over budget)
  ingredient overlap: 30 pts
  urgency boost:      20 pts  (ingredients with urgency <= 3 days)
  cuisine affinity:   10 pts
  equipment match:    10 pts
  spoonacular rating:  5 pts
"""

import json
import logging
import math
import re
from typing import Optional
from app.config import LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS, LLM_API_KEY, RANKING_MODE
from app.services.inference_client import get_client
from app.schemas import SessionContextRequest, IngredientItem

logger = logging.getLogger("app.ranking")


def _extract_json(raw: str) -> str:
    """Strip <think> blocks, markdown fences, and other wrapper text to get raw JSON."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    match = re.search(r"(\[.*\]|\{.*\})", raw, re.DOTALL)
    if match:
        return match.group(1)
    return raw

# Number of rule-scored candidates passed to the LLM in hybrid mode
_HYBRID_LLM_INPUT_SIZE = 15

_RERANK_SYSTEM_PROMPT = (
    "You are a recipe ranking assistant. "
    "Re-rank the provided recipe candidates from most to least relevant for this user. "
    "Consider: ingredient availability, perishability urgency, cuisine preference, "
    "occasion appropriateness, meal variety, and novelty. "
    "Return ONLY a JSON array of recipe IDs in ranked order (most relevant first). "
    "No explanation, no markdown."
)


def score_rules(
    recipe: dict,
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    cooking_equipment: list[str],
) -> float:
    """
    Deterministic rule-based score for a single recipe.
    Returns float('-inf') for hard-filter violations (dietary, time).

    :param recipe:               Recipe dict from pipeline (RecipeCache fields).
    :param context:              Current session context.
    :param dietary_restrictions: User's dietary restriction IDs.
    :param cuisine_preferences:  User's preferred cuisine IDs.
    :param cooking_equipment:    Equipment the user owns.
    :returns: Score 0-100, or float('-inf') if hard-filtered out.
    """
    score = 0.0

    # --- Hard filter: time ---
    total_time = recipe.get("total_time") or 0
    time_budget = context.available_time_minutes
    over = total_time - time_budget
    if over > 15:
        return float("-inf")
    if over <= 0:
        score += 25.0
    else:
        score += 25.0 * (1.0 - over / 15.0)

    # --- Hard filter: dietary restrictions ---
    if dietary_restrictions:
        restriction_set = set(r.lower() for r in dietary_restrictions)
        recipe_tags = set(t.lower() for t in (recipe.get("dietary_tags") or []))
        recipe_ingredients = " ".join(
            i.get("name", "") for i in (recipe.get("ingredients") or [])
        ).lower()
        for restriction in restriction_set:
            # Crude keyword check; Spoonacular tags cover the common cases
            if restriction == "vegan" and "vegan" not in recipe_tags:
                pass  # not a violation unless we have tag data
            if restriction in ("gluten-free", "gluten_free"):
                if "gluten" in recipe_ingredients or "wheat" in recipe_ingredients:
                    return float("-inf")
            if restriction in ("dairy-free", "dairy_free"):
                dairy_keywords = {"milk", "cheese", "butter", "cream", "yogurt"}
                if any(kw in recipe_ingredients for kw in dairy_keywords):
                    return float("-inf")
            if restriction in ("nut-free", "nut_free"):
                nut_keywords = {"almond", "walnut", "peanut", "cashew", "hazelnut", "pecan"}
                if any(kw in recipe_ingredients for kw in nut_keywords):
                    return float("-inf")

    # --- Ingredient overlap (0-30 pts) ---
    available_names = {i.name.lower() for i in context.available_ingredients}
    recipe_ingredient_names = {
        i.get("name", "").lower() for i in (recipe.get("ingredients") or [])
    }
    overlap = len(available_names & recipe_ingredient_names)
    score += min(30.0, overlap * 6.0)

    # --- Perishability urgency boost (0-20 pts) ---
    urgent_names = {
        i.name.lower() for i in context.available_ingredients
        if i.urgency is not None and i.urgency <= 3
    }
    urgency_overlap = len(urgent_names & recipe_ingredient_names)
    score += min(20.0, urgency_overlap * 10.0)

    # --- Cuisine affinity (0-10 pts) ---
    if cuisine_preferences:
        recipe_cuisine = (recipe.get("cuisine") or "").lower()
        if any(recipe_cuisine == p.lower() for p in cuisine_preferences):
            score += 10.0

    # --- Equipment match (0-10 pts) ---
    needed_equipment = set(recipe.get("cooking_equipment") or [])
    if not needed_equipment:
        score += 10.0  # no special equipment needed = full points
    elif cooking_equipment:
        have = set(e.lower() for e in cooking_equipment)
        needed = set(e.lower() for e in needed_equipment)
        if needed.issubset(have):
            score += 10.0
        else:
            score += 5.0 * (len(needed & have) / len(needed))

    # --- Spoonacular rating (0-5 pts) ---
    rating = recipe.get("rating") or 0.0
    score += min(5.0, (float(rating) / 5.0) * 5.0)

    return score


async def rank_recipes(
    recipes: list[dict],
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    cooking_equipment: list[str],
    mode: Optional[str] = None,
) -> list[dict]:
    """
    Ranks recipes using the specified mode.

    :param recipes:              Candidate recipe dicts.
    :param context:              Current session context.
    :param dietary_restrictions: Hard-filter restrictions.
    :param cuisine_preferences:  Soft-boost preferences.
    :param cooking_equipment:    Equipment the user owns.
    :param mode:                 Override ranking mode. Falls back to RANKING_MODE config.
    :returns: Ranked list of recipe dicts with 'score' field set.
    """
    effective_mode = mode or RANKING_MODE

    # Always compute rule scores first (used by all modes for hard filtering)
    scored = []
    for recipe in recipes:
        rule_score = score_rules(recipe, context, dietary_restrictions, cuisine_preferences, cooking_equipment)
        if not math.isinf(rule_score):
            scored.append({**recipe, "score": rule_score})

    scored.sort(key=lambda r: r["score"], reverse=True)
    logger.info("Rule scoring: %d/%d candidates passed hard filters (mode=%s)",
                len(scored), len(recipes), effective_mode)

    if effective_mode == "rules_only" or not LLM_BASE_URL:
        return scored

    if effective_mode == "llm_only":
        logger.info("LLM re-ranking all %d candidates", len(scored))
        return await _llm_rerank(scored, context)

    # hybrid: rules narrow to top _HYBRID_LLM_INPUT_SIZE, then LLM re-ranks those
    top = scored[:_HYBRID_LLM_INPUT_SIZE]
    rest = scored[_HYBRID_LLM_INPUT_SIZE:]
    logger.info("Hybrid: sending top %d to LLM re-ranker, keeping %d in tail", len(top), len(rest))
    reranked_top = await _llm_rerank(top, context)
    return reranked_top + rest


async def _llm_rerank(
    candidates: list[dict],
    context: SessionContextRequest,
) -> list[dict]:
    """
    Calls the LLM to re-rank candidates. Returns them in re-ranked order.
    Falls back to the input order if the LLM call fails.
    """
    if not candidates:
        return candidates

    try:
        client = get_client(base_url=LLM_BASE_URL, api_key=LLM_API_KEY or "local")

        candidate_summary = [
            {
                "id": r["id"],
                "title": r.get("title", ""),
                "cuisine": r.get("cuisine", ""),
                "total_time": r.get("total_time", 0),
                "rule_score": round(r.get("score", 0), 2),
                "ingredients": [i.get("name") for i in (r.get("ingredients") or [])[:8]],
            }
            for r in candidates
        ]

        user_message = (
            f"Meal type: {context.meal_type}\n"
            f"Time budget: {context.available_time_minutes} minutes\n"
            f"Available ingredients: {[i.name for i in context.available_ingredients]}\n"
            f"Occasion: {context.occasion or 'none'}\n\n"
            f"Candidates:\n{json.dumps(candidate_summary, indent=2)}\n\n"
            f"Return a JSON array of recipe IDs in your preferred order."
        )

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=8192,
            temperature=0.2,
            timeout=LLM_TIMEOUT_SECONDS,
        )

        raw = response.choices[0].message.content or ""
        logger.debug("Re-ranker raw response (first 500 chars): %s", raw[:500])
        clean = _extract_json(raw)
        ranked_ids: list[str] = json.loads(clean)

        # Reconstruct ordered list; append any IDs the LLM omitted at the end
        id_to_recipe = {r["id"]: r for r in candidates}
        seen = set()
        result = []
        for rid in ranked_ids:
            if rid in id_to_recipe and rid not in seen:
                result.append(id_to_recipe[rid])
                seen.add(rid)
        for r in candidates:
            if r["id"] not in seen:
                result.append(r)
        return result

    except Exception as e:
        logger.warning("LLM re-rank failed (%s: %s) — falling back to rule order", type(e).__name__, e)
        return candidates
