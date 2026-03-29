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
from app.services.inference_client import ollama_chat
from app.schemas import SessionContextRequest, IngredientItem

logger = logging.getLogger("app.llm")

# ---------------------------------------------------------------------------
# Ingredient name normalization
# ---------------------------------------------------------------------------
# Strips brand names and quality/marketing adjectives before the name is
# embedded in the LLM prompt.  If the model never *sees* "Fairlife milk" it
# cannot copy it into key_ingredients.
_QUALIFIER_RE = re.compile(
    r"\b("
    r"fairlife|kirkland|barilla|heinz|organic\s+valley|land\s+o\s+lakes|"
    r"birds\s+eye|del\s+monte|hunts?|campbells?|knorr|maggi|kikkoman|"
    r"365\s+by\s+whole\s+foods|great\s+value|store\s+brand|"
    r"grass[-\s]fed|free[-\s]range|pasture[-\s]raised|cage[-\s]free|"
    r"organic|natural|premium|artisan|gourmet|all[-\s]natural|"
    r"non[-\s]gmo|non\s+gmo|gluten[-\s]free|kosher|halal|"
    r"tri[-\s]color|multi[-\s]color|multicolor|heirloom|"
    r"purified\s+drinking|purified|distilled|filtered|sparkling|still|"
    r"whole\s+grain|whole[-\s]wheat|stone[-\s]ground|"
    r"low[-\s]fat|non[-\s]fat|fat[-\s]free|reduced[-\s]fat|full[-\s]fat|"
    r"skim|2%|1%|whole|"
    r"unsalted|lightly\s+salted|salted|unsweetened|sweetened|"
    r"extra\s+virgin|light|extra[-\s]lean|lean|extra[-\s]firm|firm|silken|"
    r"fresh|frozen|canned|tinned|jarred|dried|dehydrated|"
    r"raw|cooked|roasted|toasted|smoked|cured|pickled|"
    r"boneless|skinless|bone[-\s]in|skin[-\s]on|center[-\s]cut|"
    r"baby|mini|large|medium|small|xl|jumbo|"
    r"drinking|mineral"
    r")\s+",
    re.IGNORECASE,
)


def _normalize_ingredient_name(raw: str) -> str:
    """Strip brand names and quality qualifiers, returning the plain culinary name."""
    # Iteratively strip until no more matches (handles stacked qualifiers like
    # 'organic grass-fed ground beef')
    prev = None
    result = raw.strip()
    while result != prev:
        prev = result
        result = _QUALIFIER_RE.sub("", result).strip()
    return result or raw.strip()


def _extract_json(raw: str) -> str:
    """Strip <think> blocks, markdown fences, and other wrapper text to get raw JSON.

    Also attempts to recover truncated JSON arrays by closing open brackets.
    """
    # Remove <think>...</think> blocks (qwen3 reasoning traces)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    # Remove markdown code fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # If the response has surrounding text, try to extract the JSON array/object
    match = re.search(r"(\[.*\]|\{.*\})", raw, re.DOTALL)
    if match:
        return match.group(1)
    # Try to recover a truncated JSON array (starts with [ but never closes)
    if raw.startswith("["):
        return _fix_truncated_json_array(raw)
    return raw


def _fix_truncated_json_array(raw: str) -> str:
    """Attempt to recover a truncated JSON array by finding the last complete object."""
    # Find the last complete JSON object (ends with })
    last_brace = raw.rfind("}")
    if last_brace == -1:
        return raw
    # Truncate after the last complete object and close the array
    truncated = raw[:last_brace + 1].rstrip().rstrip(",") + "\n]"
    return truncated

_IDEATION_COUNT = 40

_SYSTEM_PROMPT = (
    "You are a recipe ideation assistant for an app whose goal is to get people "
    "genuinely excited about cooking at home. "
    "Every suggestion must be a real, crave-worthy dish — the kind of food someone "
    "would be delighted to eat, not just willing to make. "
    "Taste and culinary appeal are the highest priority. "
    "Never force unusual ingredient pairings just because an ingredient is available. "
    "When the user has ingredients that are about to expire, treat them as an opportunity: "
    "roughly 40% of your suggestions should be dishes where those expiring ingredients "
    "play a central, delicious role — not a minor addition. "
    "The remaining suggestions should focus on variety and the best possible dishes "
    "from everything available. "
    "Every dish must be a recognisable, culinarily coherent recipe. "
    "\n\n"
    "STRICT INGREDIENT RULES:\n"
    "1. key_ingredients must ONLY contain ingredients from the user's available "
    "ingredient list provided in the prompt. Do NOT invent ingredients that are "
    "not listed — if strawberries are not in the list, do not include them. "
    "It is fine to use pantry staples (salt, oil, pepper) that may not be listed, "
    "but never invent a main ingredient that is not present.\n"
    "2. Strip ALL brand names and quality descriptors from ingredient names — "
    "use only the plain culinary name a cookbook would use.\n"
    "Examples of correct stripping:\n"
    "  'Fairlife milk'              → 'milk'\n"
    "  'Kirkland grass-fed ground beef' → 'ground beef'\n"
    "  'Barilla tri-color rotini pasta' → 'rotini pasta'\n"
    "  'purified drinking water'    → 'water'\n"
    "  'grass-fed ground beef'      → 'ground beef'\n"
    "  'free-range chicken breast'  → 'chicken breast'\n"
    "The key_ingredients list must contain only plain culinary names — no brands, "
    "no certifications (organic, grass-fed, free-range, non-GMO), no packaging "
    "descriptors (purified, filtered, drinking). "
    "\n\n"
    "Output ONLY a valid JSON array. No markdown, no explanation."
    "\n\n"
    "RECIPE NAME RULES:\n"
    "The 'name' field is used verbatim as a web search query to find a real recipe. "
    "It MUST return results, so follow these rules strictly:\n"
    "1. Keep it SHORT — 2 to 5 words maximum.\n"
    "2. Use COMMON, well-known dish names that people actually search for on AllRecipes or "
    "Food Network — not invented or overly creative names.\n"
    "3. NO 'X with Y' patterns. Never append ingredients using 'with', 'and', or commas. "
    "Bad: 'Beef Stew with Potatoes and Carrots and Honey'. Good: 'Beef Stew'.\n"
    "4. NO generic adjective qualifiers at the start — no Classic, Easy, Quick, Simple, "
    "Homemade, Traditional, Authentic, Rustic, Hearty, Creamy, Crispy, Healthy, Best, Ultimate.\n"
    "5. The name must be a real dish that exists, not a forced ingredient mashup.\n"
    "GOOD names: 'Beef Stew', 'Honey Garlic Chicken', 'Pasta Bolognese', "
    "'Chicken Stir Fry', 'Mushroom Risotto', 'Vegetable Curry', 'French Toast', "
    "'Ground Beef Tacos', 'Spaghetti Carbonara', 'Banana Pancakes'.\n"
    "BAD names: 'Classic Rustic Beef Strudel with Honey and Strawberries', "
    "'Easy Homemade Tri-Color Pasta Bake with Ground Beef, Milk and Honey'.\n"
    "The key_ingredients list tells the ranker what ingredients to use — "
    "you do NOT need to cram them into the dish name."
)


def _build_user_prompt(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
) -> str:
    urgent = [
        f"{_normalize_ingredient_name(i.name)} ({i.estimated_quantity} {i.unit}, use within {i.urgency} days)"
        for i in context.available_ingredients
        if i.urgency is not None and i.urgency <= 3
    ]
    regular = [
        f"{_normalize_ingredient_name(i.name)} ({i.estimated_quantity} {i.unit})"
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

    urgency_target = int(_IDEATION_COUNT * 0.4)
    urgency_instruction = (
        f"IMPORTANT: approximately {urgency_target} of your {_IDEATION_COUNT} suggestions "
        "must feature the URGENT ingredients as a central, delicious component of the dish — "
        "not a minor garnish. Choose dishes where those ingredients genuinely shine and taste great. "
        "Never sacrifice taste to use an expiring ingredient — the dish must still be crave-worthy. "
    ) if urgent else ""

    lines.append("")
    lines.append(
        f"Generate exactly {_IDEATION_COUNT} recipe suggestions. "
        "For each return a JSON object with: "
        "\"name\" (2-5 word common recipe name as you would search on AllRecipes — "
        "NO 'with/and ingredient' suffixes, NO qualifier adjectives like Classic/Easy/Homemade, "
        "real dish names only e.g. 'Beef Stew' NOT 'Classic Beef Stew with Potatoes'), "
        "\"key_ingredients\" (list of 3-5 PLAIN generic ingredient names — "
        "strip all brands and qualifiers: 'Fairlife milk' → 'milk', "
        "'grass-fed ground beef' → 'ground beef', "
        "'tri-color rotini pasta' → 'rotini pasta', "
        "'purified drinking water' → 'water'), "
        "\"cuisine\" (string), \"estimated_time\" (integer minutes). "
        + urgency_instruction +
        "Focus on well-known, genuinely tasty dishes people would be excited to cook and eat. "
        "Suggest a variety of cuisines and styles. "
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
    user_prompt = _build_user_prompt(
        context, dietary_restrictions, cuisine_preferences, health_goal, history_titles
    )

    raw_text = await ollama_chat(
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=16384,
        temperature=0.7,
        timeout=LLM_TIMEOUT_SECONDS,
        think=False,
    )

    logger.info("LLM raw response (first 800 chars):\n%s", raw_text[:800])
    clean = _extract_json(raw_text)
    if not clean.strip():
        raise ValueError("LLM returned empty content after extraction")
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

    # Log every suggestion so the pipeline is fully traceable in the console
    logger.info("LLM ideation produced %d suggestions:", len(result))
    for i, r in enumerate(result, 1):
        logger.info(
            "  %2d. %-45s | %-18s | %3d min | ingredients: %s",
            i,
            r["name"],
            r["cuisine"],
            r["estimated_time"],
            ", ".join(r["key_ingredients"]),
        )
    return result


def _fallback_suggestions(context: SessionContextRequest) -> list[dict]:
    """
    Keyword-based fallback used when LLM is unavailable.
    Returns ingredient names directly as search terms for the recipe fetcher.
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


# ---------------------------------------------------------------------------
# Ingredient substitution via LLM
# ---------------------------------------------------------------------------

_SUBSTITUTION_PROMPT = """\
You are a helpful cooking assistant. Given a recipe's ingredients and a list of ingredients the user already has, identify which recipe ingredients the user is MISSING, and suggest a practical substitution from the user's available ingredients or common pantry staples.

Recipe ingredients:
{recipe_ingredients}

User has these ingredients available:
{user_ingredients}

Return a JSON array of objects. Each object represents ONE recipe ingredient and has these fields:
- "ingredient": the recipe ingredient name (exactly as listed)
- "have": true if the user has this ingredient (or a very close match), false otherwise
- "substitution": if have is false and a good swap exists, a short string like "use <X> instead". If no good substitution exists, null.

Rules:
- Match loosely: "chicken breast" matches "chicken", "olive oil" matches "oil", etc.
- Only suggest substitutions that genuinely work in cooking (e.g. lime for lemon, Greek yogurt for sour cream, any pasta shape for another).
- If the user doesn't have a substitute, set substitution to null.
- Return ONLY the JSON array, no explanation.
"""


async def suggest_substitutions(
    recipe_ingredients: list[str],
    user_ingredients: list[str],
) -> list[dict]:
    """
    Ask the LLM to match recipe ingredients against the user's pantry and
    suggest substitutions for missing items.

    Returns a list of dicts: [{ingredient, have, substitution}, ...]
    Falls back to empty list if LLM is unavailable.
    """
    if not LLM_BASE_URL or not recipe_ingredients:
        return []

    prompt = _SUBSTITUTION_PROMPT.format(
        recipe_ingredients="\n".join(f"- {ing}" for ing in recipe_ingredients),
        user_ingredients="\n".join(f"- {ing}" for ing in user_ingredients) if user_ingredients else "(none listed)",
    )

    try:
        raw = await ollama_chat(
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.3,
            timeout=float(LLM_TIMEOUT_SECONDS),
            think=False,
        )
        cleaned = _extract_json(raw)
        results = json.loads(cleaned)
        if isinstance(results, list):
            logger.info("LLM substitution: %d ingredients analysed", len(results))
            return results
        logger.warning("LLM substitution returned non-list: %s", type(results))
        return []
    except Exception as exc:
        logger.warning("LLM substitution failed: %s", exc)
        return []
