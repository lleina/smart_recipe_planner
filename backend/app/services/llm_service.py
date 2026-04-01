"""
LLM ideation service — generates recipe name suggestions from session context.

Uses any OpenAI-compatible text endpoint configured via ``LLM_BASE_URL`` and
``LLM_MODEL``. Falls back to a curated keyword list when the LLM is not
configured, enabling development without a running Ollama instance.

Public API:
    ``ideate_recipes(context, dietary_restrictions, ...)``
        Returns a list of ~25 recipe suggestion dicts for the pipeline.
    ``suggest_substitutions(recipe_ingredients, user_ingredients)``
        Returns ingredient match and substitution suggestions for a recipe card.

Default model: qwen3:4b (via Ollama, native ``/api/chat`` endpoint).
"""

import json
import logging
import re
import httpx
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


def _normalize_ingredient_name(raw_name: str) -> str:
    """Strip brand names and quality qualifiers, returning the plain culinary name.

    Iteratively applies the qualifier regex until no more matches are found.
    This handles stacked qualifiers like ``"organic grass-fed ground beef"`` →
    ``"ground beef"`` in two passes.

    Args:
        raw_name: Ingredient name as entered by the user or returned by the VLM,
            potentially containing brand names or marketing adjectives.

    Returns:
        The plain culinary name a cookbook would use (e.g. ``"ground beef"``).
        Falls back to the stripped input if the regex removes everything.
    """
    previous = None
    normalized = raw_name.strip()
    while normalized != previous:
        previous = normalized
        normalized = _QUALIFIER_RE.sub("", normalized).strip()
    return normalized or raw_name.strip()


def _extract_json(raw: str) -> str:
    """Strip <think> blocks, markdown fences, and other wrapper text to get raw JSON.

    Also attempts to recover truncated JSON arrays by closing open brackets.
    """
    # Remove <think>...</think> blocks (qwen3 reasoning traces)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    # Remove markdown code fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    # Find where a JSON array/object begins (skip any preamble text)
    arr_start = raw.find("[")
    obj_start = raw.find("{")

    if arr_start != -1 and (obj_start == -1 or arr_start <= obj_start):
        # Array output — always apply truncation recovery.
        # NEVER use a greedy \[.*\] regex: on truncated output it matches up to
        # an inner key_ingredients ']' and returns malformed JSON.
        candidate = raw[arr_start:]
        return _fix_truncated_json_array(candidate)

    if obj_start != -1:
        # Single object — use non-greedy extraction
        match = re.search(r"\{[^{]*\}", raw, re.DOTALL)
        if match:
            return match.group(0)

    return raw


def _fix_truncated_json_array(raw_json: str) -> str:
    """Attempt to recover a truncated JSON array by closing it at the last complete object.

    The LLM occasionally truncates its output mid-array when approaching the
    token limit. This function finds the last complete JSON object (the last
    ``}``) and appends a closing bracket to produce valid JSON.

    Args:
        raw_json: Potentially truncated JSON array string starting with ``[``.

    Returns:
        A syntactically closed JSON array string. If no ``}`` is found,
        returns the input unchanged (the caller will raise on ``json.loads``).
    """
    last_closing_brace_index = raw_json.rfind("}")
    if last_closing_brace_index == -1:
        return raw_json
    return raw_json[:last_closing_brace_index + 1].rstrip().rstrip(",") + "\n]"


# Number of recipe suggestions to generate per LLM ideation call.
_IDEATION_COUNT = 80
# Maximum attempts to call the LLM before falling back to the keyword list.
_MAX_LLM_RETRIES = 3

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
    "The ONLY pantry staples you may assume the user has (even if not listed) are: "
    "salt, black pepper, cooking oil, and vinegar. Do NOT assume the user has "
    "flour, sugar, baking powder, baking soda, cornstarch, spices, seasonings, "
    "or any other ingredients unless they are explicitly listed.\n"
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
)


def _build_user_prompt(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
    cooking_equipment: list[str] | None = None,
) -> str:
    """Build the user-turn prompt for the LLM recipe ideation call.

    Formats all session context fields into a structured prompt that specifies
    the exact output format, ingredient constraints, and distribution rules the
    LLM must follow.

    Args:
        context: The user's session context (meal type, time, ingredients, etc.).
        dietary_restrictions: Hard constraints (e.g. "vegetarian", "gluten-free").
        cuisine_preferences: Preferred cuisine types (soft guidance).
        health_goal: User's health goal string (e.g. "high-protein").
        history_titles: Titles of recently cooked recipes to exclude.
        cooking_equipment: Available kitchen equipment for hard filtering.

    Returns:
        A formatted multi-section string ready to send as the ``user`` message.
    """
    urgent = [
        f"{_normalize_ingredient_name(i.name)} (use within {i.urgency} day{'s' if i.urgency != 1 else ''})"
        for i in context.available_ingredients
        if i.urgency is not None and i.urgency <= 3
    ]
    regular = [
        f"{_normalize_ingredient_name(i.name)} ({i.estimated_quantity} {i.unit})"
        for i in context.available_ingredients
        if i.urgency is None or i.urgency > 3
    ]

    # --- Build structured prompt ---
    sections = []

    # Header
    sections.append("You are a professional chef and recipe curator.\n"
                    "Your task is to generate HIGH-QUALITY, CRAVE-WORTHY recipes that a user would realistically want to cook GIVEN the constraints below.")
    sections.append("-------------------------------------")
    sections.append("INPUT CONSTRAINTS")
    sections.append("-------------------------------------")
    sections.append(f"Meal type: {context.meal_type}")
    sections.append(f"Total time budget: {context.available_time_minutes} minutes")
    sections.append(f"Servings: {context.serving_count}")
    if context.occasion:
        sections.append(f"Occasion: {context.occasion}")

    # Ingredients
    sections.append("")
    if urgent:
        sections.append("URGENT ingredients (prioritize using these well):")
        for u in urgent:
            sections.append(f"- {u}")
    if regular:
        sections.append("\nOther ingredients:")
        for r in regular:
            sections.append(f"- {r}")

    # Equipment
    sections.append("")
    if cooking_equipment:
        sections.append(f"Available equipment (HARD CONSTRAINT):")
        sections.append(", ".join(cooking_equipment))
        sections.append("")
        sections.append("You MUST NOT suggest any recipe that is too difficult when missing the available cooking equipment. For example, if blender isn't in the list, then do not suggest smoothies or pureed soups that require a blender, as that would lead to user frustration. If an ingredient can be prepared with a simple hand tool (e.g. garlic can be minced with a knife instead of a food processor), then it is fine to suggest recipes using that ingredient even if the user doesn't have the ideal equipment — just make sure the recipe is still realistic and delicious without it. But if a recipe truly requires a specific piece of equipment to be successful, and the user doesn't have it, then do NOT suggest that recipe.")
    else:
        sections.append(
            "No special cooking equipment listed. Only suggest recipes that can be made with "
            "basic stovetop and common hand tools (pot, pan, spatula, whisk, knife, cutting board)."
        )

    # Dietary restrictions
    if dietary_restrictions:
        sections.append(f"\nDietary restrictions (NEVER violate): {', '.join(dietary_restrictions)}")

    # Cuisines
    if cuisine_preferences:
        cuisine_str = ", ".join(cuisine_preferences)
        sections.append(f"\nPreferred cuisines: {cuisine_str}")

    # Health goal
    if health_goal and health_goal != "none":
        sections.append(f"\nHealth goal: {health_goal}")

    # History
    if history_titles:
        recent = history_titles[:5]
        sections.append("\nRecently cooked (DO NOT repeat or closely duplicate):")
        for title in recent:
            sections.append(f"- {title}")

    # --- Generation requirements ---
    sections.append("")
    sections.append("-------------------------------------")
    sections.append("GENERATION REQUIREMENTS")
    sections.append("-------------------------------------")
    sections.append("")
    sections.append(f"You must generate EXACTLY {_IDEATION_COUNT} recipes.")

    # Distribution constraints
    sections.append("")
    sections.append("### Distribution constraints:")
    if urgent:
        urgency_target = int(_IDEATION_COUNT * 0.4)
        sections.append(
            f"- EXACTLY {urgency_target} recipes must prominently feature at least ONE urgent ingredient"
        )
    if cuisine_preferences:
        cuisine_target = int(_IDEATION_COUNT * 0.6)
        sections.append(
            f"- At least {cuisine_target} recipes ({int(cuisine_target / _IDEATION_COUNT * 100)}%) "
            f"must be {', '.join(cuisine_preferences)}"
        )
        sections.append("- Remaining recipes can be any cuisine for variety")

    # Quality rules
    sections.append("")
    sections.append("### Quality rules:")
    sections.append("- Recipes must be REAL, recognizable dishes (not invented combinations)")
    sections.append("- No awkward or forced ingredient usage")
    if urgent:
        sections.append("- Urgent ingredients must be a CORE component, not garnish")
    sections.append(f"- Recipes must realistically be completable in ≤{context.available_time_minutes} minutes")
    sections.append(f"- Recipes must make sense as a {context.meal_type.upper()}")
    sections.append("- Focus on well-known, genuinely tasty dishes people would be excited to cook and eat")
    sections.append("- Never sacrifice taste to use an expiring ingredient — the dish must still be crave-worthy")

    # Output format
    sections.append("")
    sections.append("-------------------------------------")
    sections.append("OUTPUT FORMAT (STRICT)")
    sections.append("-------------------------------------")
    sections.append("")
    sections.append(f"Return ONLY a JSON array of {_IDEATION_COUNT} objects.")
    sections.append("CRITICAL: Output COMPACT JSON — no indentation, no extra whitespace. One recipe object per line.")
    sections.append("")
    sections.append("Each object MUST have exactly these 4 keys:")
    sections.append('  {"name": "...", "key_ingredients": ["..."], "cuisine": "...", "estimated_time": 0}')
    sections.append("")
    sections.append("Fields:")
    sections.append('  name: 2-5 word real dish name (Creamy/Spicy/Crispy/Smoky descriptors OK, no marketing fluff)')
    sections.append('  key_ingredients: array of 3-5 plain ingredient names (no brands, no descriptors)')
    sections.append('  cuisine: cuisine string')
    sections.append('  estimated_time: integer minutes (realistic total time)')

    # Naming rules
    sections.append("")
    sections.append("-------------------------------------")
    sections.append("NAMING RULES")
    sections.append("-------------------------------------")
    sections.append("- Use the name someone would actually type into Google to find this recipe.")
    sections.append("- Evocative culinary descriptors ARE allowed and encouraged: Creamy, Spicy, Crispy, Smoky, Garlic Butter, Honey Glazed, Pan-Fried, etc.")
    sections.append("  These make searches more specific and help find the right recipe. Example: 'Creamy Gochujang Pasta', 'Crispy Garlic Tofu', 'Smoky Black Bean Soup'")
    sections.append('- NO "with/and" connector phrases (bad: "Pasta with Tomato Sauce", good: "Tomato Pasta")')
    sections.append("- NO pure marketing fluff: Best, Ultimate, Amazing, Incredible, Favorite, Foolproof, World's")
    sections.append("- NO process adjectives that add no meaning: Easy, Quick, Simple, Homemade, Classic")
    sections.append("- Cuisine-adjectives (Korean, Italian, Thai, Mexican) are allowed when they change the dish identity")

    # Time estimation rules
    sections.append("")
    sections.append("-------------------------------------")
    sections.append("TIME ESTIMATION RULES (CRITICAL)")
    sections.append("-------------------------------------")
    sections.append("- estimated_time must reflect REALISTIC total cooking time including all steps")
    sections.append("- Include: prep, marinating, simmering, baking, resting, braising, slow-cooking")
    sections.append("- A braise or stew is NOT 25 minutes — it is typically 2–4 hours")
    sections.append("- Caramelizing onions takes 30–45 minutes alone")
    sections.append("- Do NOT underestimate. Users rely on these times to plan their meals")
    sections.append(f"- ONLY suggest recipes that can genuinely be completed within {context.available_time_minutes} minutes")

    # Validation
    sections.append("")
    sections.append("-------------------------------------")
    sections.append("VALIDATION BEFORE OUTPUT")
    sections.append("-------------------------------------")
    sections.append("")
    sections.append("Before returning, internally verify:")
    sections.append(f"1. Total recipes = {_IDEATION_COUNT}")
    if urgent:
        sections.append(f"2. Urgent recipes = exactly {int(_IDEATION_COUNT * 0.4)}")
    if cuisine_preferences:
        sections.append(f"3. ≥{int(_IDEATION_COUNT * 0.6)} recipes are {'/'.join(cuisine_preferences)}")
    sections.append("4. NO forbidden equipment implied")
    sections.append("5. NO duplicate or near-duplicate dishes")
    sections.append(f"6. All recipes ≤ {context.available_time_minutes} minutes (realistically)")
    sections.append("7. All names follow naming rules")
    sections.append("8. All estimated_time values are REALISTIC (not underestimated)")
    sections.append("")
    sections.append("If any condition fails, fix it before output.")
    sections.append("")
    sections.append("Return ONLY the JSON array.")

    return "\n".join(sections)


async def ideate_recipes(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
    cooking_equipment: list[str] | None = None,
) -> tuple[list[dict], str | None]:
    """Generate recipe name suggestions using the configured LLM.

    Calls the LLM up to ``_MAX_LLM_RETRIES + 1`` times, retrying on parse
    errors or when too few suggestions are returned. Falls back to a curated
    keyword list when the LLM is unavailable or all retries fail.

    Args:
        context: Session context (meal type, time budget, available ingredients).
        dietary_restrictions: Hard constraints (e.g. "vegan", "gluten-free").
        cuisine_preferences: Soft cuisine preferences for distribution guidance.
        health_goal: User's stated health goal (e.g. "high-protein", "none").
        history_titles: Recently cooked recipe titles to exclude from suggestions.
        cooking_equipment: Available equipment for hard filtering in the prompt.

    Returns:
        Tuple of ``(suggestions, llm_warning)``. ``llm_warning`` is a
        user-facing string when a connectivity fallback was triggered,
        ``None`` on success.
    """
    if not LLM_BASE_URL:
        logger.info("LLM_BASE_URL not set — returning fallback suggestions")
        return _fallback_suggestions(context), None

    llm_warning: str | None = None
    for attempt in range(_MAX_LLM_RETRIES + 1):
        try:
            logger.info("Calling LLM (%s) for %d suggestions (meal=%s, time=%dmin) [attempt %d/%d]",
                        LLM_MODEL, _IDEATION_COUNT, context.meal_type,
                        context.available_time_minutes, attempt + 1, _MAX_LLM_RETRIES + 1)
            parsed_suggestions = await _call_llm(
                context, dietary_restrictions, cuisine_preferences,
                health_goal, history_titles, cooking_equipment or []
            )
            if len(parsed_suggestions) >= 5:
                logger.info("LLM returned %d suggestions", len(parsed_suggestions))
                return parsed_suggestions, None
            logger.warning(
                "LLM returned only %d suggestions (attempt %d/%d) — retrying",
                len(parsed_suggestions), attempt + 1, _MAX_LLM_RETRIES + 1,
            )
        except (json.JSONDecodeError, ValueError) as parse_error:
            if attempt < _MAX_LLM_RETRIES:
                logger.warning(
                    "LLM parse error (%s: %s) — retrying (attempt %d/%d)",
                    type(parse_error).__name__, parse_error,
                    attempt + 1, _MAX_LLM_RETRIES + 1,
                )
                continue
            logger.warning(
                "LLM ideation failed after %d attempts (%s: %s) — using fallback",
                _MAX_LLM_RETRIES + 1, type(parse_error).__name__, parse_error,
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError, OSError) as conn_err:
            logger.warning(
                "LLM unavailable (%s: %s) — using fallback suggestions",
                type(conn_err).__name__, conn_err,
            )
            llm_warning = "AI suggestions unavailable — showing popular matches"
            break
        # All other exceptions propagate — code bugs must not be silently swallowed
    return _fallback_suggestions(context), llm_warning


async def _call_llm(
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    health_goal: str,
    history_titles: list[str],
    cooking_equipment: list[str] | None = None,
) -> list[dict]:
    """Call the LLM and parse the response into a list of suggestion dicts.

    Applies JSON extraction and truncation recovery before parsing. Normalises
    the ``estimated_time`` field from either an integer or a string like
    ``"25 minutes"`` to a plain integer.

    Args:
        context: Session context for the ideation prompt.
        dietary_restrictions: Hard dietary constraints.
        cuisine_preferences: Soft cuisine preferences.
        health_goal: User's health goal string.
        history_titles: Recipe titles to exclude from suggestions.
        cooking_equipment: Available kitchen equipment.

    Returns:
        List of normalised suggestion dicts ready for the pipeline.

    Raises:
        json.JSONDecodeError: If the LLM response cannot be parsed as JSON
            even after truncation recovery.
        ValueError: If the LLM returns empty content.
    """
    user_prompt = _build_user_prompt(
        context, dietary_restrictions, cuisine_preferences, health_goal, history_titles,
        cooking_equipment=cooking_equipment or [],
    )

    logger.info("[LLM ideation] FULL PROMPT SENT TO %s:\n%s", LLM_MODEL, user_prompt)

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
        priority="normal",
    )

    logger.info("LLM raw response (first 800 chars):\n%s", raw_text[:800])
    clean = _extract_json(raw_text)
    if not clean.strip():
        raise ValueError("LLM returned empty content after extraction")
    try:
        suggestions = json.loads(clean)
    except json.JSONDecodeError:
        # Inline recovery: _extract_json already applied truncation repair, but
        # the content might still be invalid (e.g. mid-string truncation). Try
        # one final aggressive strip: drop everything after the last complete
        # '}' and close the array.
        recovered = _fix_truncated_json_array(clean)
        logger.warning("Primary parse failed — attempting inline truncation recovery")
        suggestions = json.loads(recovered)  # raise if still broken

    # Normalise keys and drop malformed entries.
    # estimated_time may arrive as "25 minutes" or 25 — always coerce to int.
    parsed_suggestions: list[dict] = []
    for raw_suggestion in suggestions:
        if not isinstance(raw_suggestion, dict) or not raw_suggestion.get("name"):
            continue
        raw_time = raw_suggestion.get("estimated_time", context.available_time_minutes)
        if isinstance(raw_time, str):
            time_digits = re.search(r"\d+", raw_time)
            raw_time = int(time_digits.group()) if time_digits else context.available_time_minutes
        parsed_suggestions.append({
            "name": str(raw_suggestion["name"]),
            "key_ingredients": list(raw_suggestion.get("key_ingredients", [])),
            "cuisine": str(raw_suggestion.get("cuisine", "")),
            "estimated_time": int(raw_time),
        })

    # Log every suggestion for full pipeline traceability in the server log.
    logger.info("LLM ideation produced %d suggestions:", len(parsed_suggestions))
    for rank, suggestion in enumerate(parsed_suggestions, 1):
        logger.info(
            "  %2d. %-45s | %-18s | %3d min | ingredients: %s",
            rank,
            suggestion["name"],
            suggestion["cuisine"],
            suggestion["estimated_time"],
            ", ".join(suggestion["key_ingredients"]),
        )
    return parsed_suggestions


_FALLBACK_RECIPE_NAMES = [
    ("Chicken Stir Fry", "asian", 20),
    ("Beef Tacos", "mexican", 25),
    ("Pasta Bolognese", "italian", 35),
    ("Chicken Fried Rice", "chinese", 25),
    ("Vegetable Soup", "american", 40),
    ("Grilled Cheese Sandwich", "american", 15),
    ("Scrambled Eggs", "american", 10),
    ("Spaghetti Carbonara", "italian", 25),
    ("Chicken Curry", "indian", 40),
    ("Beef Stew", "american", 60),
    ("Banana Pancakes", "american", 20),
    ("Caesar Salad", "american", 15),
    ("Tomato Soup", "american", 30),
    ("Omelette", "french", 10),
    ("Chicken Quesadillas", "mexican", 20),
    ("Shrimp Stir Fry", "asian", 20),
    ("Mac and Cheese", "american", 25),
    ("Vegetable Curry", "indian", 35),
    ("Chicken Soup", "american", 45),
    ("Beef Burgers", "american", 20),
    ("Lemon Pasta", "italian", 20),
    ("Fried Rice", "chinese", 20),
    ("Mushroom Risotto", "italian", 40),
    ("Chicken Salad", "american", 15),
    ("French Toast", "american", 15),
    ("Ground Beef Tacos", "mexican", 20),
    ("Vegetable Stir Fry", "asian", 20),
    ("Chicken Fajitas", "mexican", 25),
    ("Tuna Pasta", "italian", 20),
    ("Egg Fried Rice", "chinese", 20),
    ("Garlic Butter Chicken", "american", 25),
    ("Lentil Soup", "mediterranean", 35),
    ("Chicken Wrap", "american", 15),
    ("Shakshuka", "middle eastern", 25),
    ("Beef Stir Fry", "asian", 20),
    ("Pesto Pasta", "italian", 20),
    ("Chicken Noodle Soup", "american", 40),
    ("Veggie Omelette", "french", 15),
    ("Sausage Pasta", "italian", 30),
    ("Avocado Toast", "american", 10),
]


def _fallback_suggestions(context: SessionContextRequest) -> list[dict]:
    """
    Keyword-based fallback used when LLM is unavailable.
    Uses a curated list of real, searchable recipe names.
    """
    ingredient_names = [i.name for i in context.available_ingredients]
    time_budget = context.available_time_minutes

    result = []
    for name, cuisine, est_time in _FALLBACK_RECIPE_NAMES:
        if est_time <= time_budget + 10:  # allow 10 min over budget
            result.append({
                "name": name,
                "key_ingredients": ingredient_names[:3] if ingredient_names else [],
                "cuisine": cuisine,
                "estimated_time": est_time,
            })
        if len(result) >= _IDEATION_COUNT:
            break

    # If time budget is very tight, still return at least some suggestions
    if len(result) < 5:
        result = []
        for name, cuisine, est_time in _FALLBACK_RECIPE_NAMES[:_IDEATION_COUNT]:
            result.append({
                "name": name,
                "key_ingredients": ingredient_names[:3] if ingredient_names else [],
                "cuisine": cuisine,
                "estimated_time": est_time,
            })

    return result[:_IDEATION_COUNT]


# ---------------------------------------------------------------------------
# Ingredient substitution via LLM
# ---------------------------------------------------------------------------

_SUBSTITUTION_PROMPT = """\
You are a helpful cooking assistant. Given a recipe's ingredients and a list of ingredients the user has, identify what the user is MISSING and suggest practical substitutions.

Recipe ingredients:
{recipe_ingredients}

User has these ingredients:
{user_ingredients}

IMPORTANT — the user ALWAYS has these universal pantry staples, even if not listed above:
salt, sea salt, kosher salt, black pepper, white pepper, ground pepper, vegetable oil, canola oil, olive oil, extra virgin olive oil, white vinegar, apple cider vinegar, red wine vinegar, water.
Mark any of these as "have: true" automatically.
Do NOT assume the user has: flour, sugar, baking soda, baking powder, cornstarch, 
garlic powder, onion powder, paprika, cumin, cinnamon, oregano, basil, thyme, 
chili powder, cayenne pepper, red pepper flakes, turmeric, nutmeg, italian seasoning, 
butter, milk, eggs, cream, cheese, honey, soy sauce, vanilla extract, or any fresh 
produce/perishables unless explicitly listed.

Return a JSON array of objects. Each object represents ONE recipe ingredient:
- "ingredient": the recipe ingredient name (exactly as listed)
- "have": true if the user has this ingredient or a close match, false otherwise
- "substitution": if have is false and a good swap exists, a short string like "use <X> instead" or "any <Y> works". null if no good substitute.

Rules for matching:
- "have: true" ONLY when the user actually has the ingredient or an equivalent form (e.g., "chicken" matches "chicken breast", "whole milk" matches "milk"). Do NOT assume the user has something they didn't list.
- Pantry staples listed above are always "have: true".
- ALL pasta shapes are interchangeable: penne → rigatoni, spaghetti → linguine, fusilli → rotini, fettuccine → tagliatelle, farfalle → rotini, etc. If the user has ANY pasta the recipe's pasta requirement is "have: true" with a note like "use [their pasta] instead".
- Dairy swaps: milk ↔ plant milk, sour cream ↔ Greek yogurt, heavy cream ↔ coconut cream, etc.
- Acid swaps: lemon juice ↔ lime juice ↔ white wine vinegar (small amounts).
- Only suggest substitutions that genuinely work in cooking.
- Keep substitution strings SHORT (under 12 words).
- Return ONLY the JSON array, no explanation.
"""


async def suggest_substitutions(
    recipe_ingredients: list[str],
    user_ingredients: list[str],
) -> list[dict]:
    """Ask the LLM to match recipe ingredients against the user's pantry.

    For each recipe ingredient, determines whether the user has it (or a
    close equivalent) and, if not, suggests a practical substitution from
    the user's available ingredients or a generic alternative.

    Args:
        recipe_ingredients: Full ingredient list from the scraped recipe.
        user_ingredients: Ingredients the user has available.

    Returns:
        List of dicts, each with keys ``ingredient`` (str), ``have`` (bool),
        and ``substitution`` (str or None). Returns an empty list if the LLM
        is unavailable or the recipe has no ingredients.
    """
    if not LLM_BASE_URL or not recipe_ingredients:
        return []

    prompt = _SUBSTITUTION_PROMPT.format(
        recipe_ingredients="\n".join(f"- {ing}" for ing in recipe_ingredients),
        user_ingredients="\n".join(f"- {ing}" for ing in user_ingredients) if user_ingredients else "(none listed)",
    )

    logger.info("[LLM substitution] FULL PROMPT SENT TO %s:\n%s", LLM_MODEL, prompt)

    try:
        raw_response_text = await ollama_chat(
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.3,
            timeout=float(LLM_TIMEOUT_SECONDS),
            think=False,
            priority="high",
        )
        cleaned_json = _extract_json(raw_response_text)
        results = json.loads(cleaned_json)
        if isinstance(results, list):
            logger.info("LLM substitution: %d ingredients analysed", len(results))
            return results
        logger.warning("LLM substitution returned non-list: %s", type(results))
        return []
    except Exception as exc:
        logger.warning("LLM substitution failed: %s", exc)
        return []
