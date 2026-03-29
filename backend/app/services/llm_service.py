"""
LLM ideation service - generates recipe suggestions from user context.

Uses any OpenAI-compatible text endpoint configured via LLM_BASE_URL and
LLM_MODEL in config. Falls back to keyword list when LLM is not configured.

Default model: qwen3:4b (via Ollama).
"""

import json
import logging
import re
from app.config import LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS, LLM_API_KEY
from app.services.inference_client import get_client
from app.schemas import SessionContextRequest, IngredientItem

logger = logging.getLogger("app.llm")


def _extract_json(raw: str) -> str:
    """Strip <think> blocks, markdown fences, and other wrapper text to get raw JSON."""
    # Remove <think>...</think> blocks (qwen3 reasoning traces)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    # Remove markdown code fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # If the response has surrounding text, try to extract the JSON array/object
    match = re.search(r"(\[.*\]|\{.*\})", raw, re.DOTALL)
    if match:
        return match.group(1)
    return raw

_IDEATION_COUNT = 10

_SYSTEM_PROMPT = (
    "You are a recipe ideation assistant. "
    "Given a user's available ingredients, dietary restrictions, meal type, "
    "and time budget, suggest recipe ideas they can actually make. "
    "Output ONLY a valid JSON array. No markdown, no explanation."
)


def _build_user_prompt(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
) -> str:
    urgent = [
        f"{i.name} ({i.estimated_quantity} {i.unit}, use within {i.urgency} days)"
        for i in context.available_ingredients
        if i.urgency is not None and i.urgency <= 3
    ]
    regular = [
        f"{i.name} ({i.estimated_quantity} {i.unit})"
        for i in context.available_ingredients
        if i.urgency is None or i.urgency > 3
    ]

    lines = [
        f"Meal type: {context.meal_type}",
        f"Total time budget: {context.available_time_minutes} minutes",
        f"Servings needed: {context.serving_count}",
    ]
    if context.occasion:
        lines.append(f"Occasion: {context.occasion}")
    if urgent:
        lines.append(f"URGENT ingredients (use soon): {', '.join(urgent)}")
    if regular:
        lines.append(f"Other available ingredients: {', '.join(regular)}")
    if dietary_restrictions:
        lines.append(f"Dietary restrictions (NEVER violate): {', '.join(dietary_restrictions)}")
    if cuisine_preferences:
        lines.append(f"Preferred cuisines: {', '.join(cuisine_preferences)}")
    if health_goal and health_goal != "none":
        lines.append(f"Health goal: {health_goal}")
    if history_titles:
        recent = history_titles[:5]
        lines.append(f"Recently cooked (avoid exact repeats): {', '.join(recent)}")

    lines.append("")
    lines.append(
        f"Generate exactly {_IDEATION_COUNT} recipe suggestions. "
        "For each return a JSON object with: "
        "\"name\" (string), \"key_ingredients\" (list of 3-5 strings), "
        "\"cuisine\" (string), \"estimated_time\" (integer minutes). "
        "Prioritize recipes that use the URGENT ingredients. "
        "Ensure every suggestion respects the dietary restrictions. "
        "Return ONLY a JSON array."
    )
    return "\n".join(lines)


async def ideate_recipes(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
) -> list[dict]:
    """
    Calls the configured LLM to generate recipe suggestions.
    Returns a list of dicts with keys: name, key_ingredients, cuisine, estimated_time.
    Falls back to keyword-based suggestions when LLM is not configured.
    """
    if not LLM_BASE_URL:
        logger.info("LLM_BASE_URL not set — returning fallback suggestions")
        return _fallback_suggestions(context)

    try:
        logger.info("Calling LLM (%s) for %d suggestions (meal=%s, time=%dmin)",
                    LLM_MODEL, _IDEATION_COUNT, context.meal_type, context.available_time_minutes)
        result = await _call_llm(context, dietary_restrictions, cuisine_preferences, health_goal, history_titles)
        logger.info("LLM returned %d suggestions", len(result))
        return result
    except Exception as e:
        logger.warning("LLM ideation failed (%s: %s) — using fallback", type(e).__name__, e)
        return _fallback_suggestions(context)


async def _call_llm(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
) -> list[dict]:
    client = get_client(base_url=LLM_BASE_URL, api_key=LLM_API_KEY or "local")
    user_prompt = _build_user_prompt(
        context, dietary_restrictions, cuisine_preferences, health_goal, history_titles
    )

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=16384,
        temperature=0.7,
        timeout=LLM_TIMEOUT_SECONDS,
    )

    raw_text = response.choices[0].message.content or ""
    logger.debug("LLM raw response (first 500 chars): %s", raw_text[:500])
    clean = _extract_json(raw_text)
    suggestions = json.loads(clean)

    # Normalise keys and drop malformed entries
    result = []
    for s in suggestions:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        # estimated_time may come as "25 minutes" or 25 — extract the integer
        raw_time = s.get("estimated_time", context.available_time_minutes)
        if isinstance(raw_time, str):
            digits = re.search(r"\d+", raw_time)
            raw_time = int(digits.group()) if digits else context.available_time_minutes
        result.append({
            "name": str(s["name"]),
            "key_ingredients": list(s.get("key_ingredients", [])),
            "cuisine": str(s.get("cuisine", "")),
            "estimated_time": int(raw_time),
        })
    return result


def _fallback_suggestions(context: SessionContextRequest) -> list[dict]:
    """
    Keyword-based fallback used when LLM is unavailable.
    Returns ingredient names directly as search terms for Spoonacular.
    """
    ingredient_names = [i.name for i in context.available_ingredients]
    base = [
        {"name": f"{context.meal_type.capitalize()} bowl", "key_ingredients": ingredient_names[:3],
         "cuisine": "american", "estimated_time": context.available_time_minutes},
        {"name": "Stir fry", "key_ingredients": ingredient_names[:3],
         "cuisine": "asian", "estimated_time": min(20, context.available_time_minutes)},
        {"name": "Pasta", "key_ingredients": ingredient_names[:2],
         "cuisine": "italian", "estimated_time": min(30, context.available_time_minutes)},
        {"name": "Salad", "key_ingredients": ingredient_names[:3],
         "cuisine": "mediterranean", "estimated_time": min(15, context.available_time_minutes)},
        {"name": "Soup", "key_ingredients": ingredient_names[:4],
         "cuisine": "american", "estimated_time": min(45, context.available_time_minutes)},
    ]
    # Pad to _IDEATION_COUNT with generic entries
    while len(base) < _IDEATION_COUNT:
        base.append({
            "name": f"Recipe {len(base) + 1}",
            "key_ingredients": ingredient_names[:2] if ingredient_names else ["pasta"],
            "cuisine": "american",
            "estimated_time": context.available_time_minutes,
        })
    return base[:_IDEATION_COUNT]
