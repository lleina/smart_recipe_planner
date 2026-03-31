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
  ingredient overlap: 40 pts  (fuzzy token match, pantry staples auto-counted)
  key ingredient gap: -12 pts each (up to -36; missing main protein/component)
  urgency boost:      10 pts  (ingredients with urgency <= 3 days)
  cuisine affinity:   15 pts
  equipment match:    10 pts
  recipe rating:       5 pts
"""

import json
import logging
import math
import re
from typing import Optional
from app.config import LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS, LLM_API_KEY, RANKING_MODE
from app.services.inference_client import ollama_chat
from app.schemas import SessionContextRequest, IngredientItem

logger = logging.getLogger("app.ranking")


def _extract_json(raw: str) -> str:
    """Strip <think> blocks, markdown fences, and other wrapper text to get raw JSON.

    Also attempts to recover truncated JSON arrays by closing open brackets.
    """
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    match = re.search(r"(\[.*\]|\{.*\})", raw, re.DOTALL)
    if match:
        return match.group(1)
    # Try to recover a truncated JSON array
    if raw.startswith("["):
        last_brace = raw.rfind("}")
        if last_brace != -1:
            return raw[:last_brace + 1].rstrip().rstrip(",") + "\n]"
    return raw

# Number of rule-scored candidates passed to the LLM in hybrid mode
_HYBRID_LLM_INPUT_SIZE = 15

_RERANK_SYSTEM_PROMPT = (
    "You are a recipe ranking assistant. "
    "Re-rank the provided recipe candidates from most to least relevant for this user. "
    "Consider: overall tastiness and appeal, ingredient availability, cuisine preference, "
    "occasion appropriateness, meal variety, and novelty. "
    "Perishable-ingredient usage is a minor tiebreaker — never rank a less appetising dish "
    "above a more appealing one solely because it uses an expiring ingredient. "
    "Return ONLY a JSON array of recipe IDs in ranked order (most relevant first). "
    "No explanation, no markdown."
)

# ── Fuzzy ingredient matching helpers ──────────────────────────────────────

# Universal pantry staples — ONLY the absolute basics every kitchen has.
# The user has explicitly requested: salt, black pepper, oil, vinegar.
# Do NOT assume flour, sugar, baking soda, seasonings, or any other items.
PANTRY_STAPLES: set[str] = {
    # salt
    "salt", "sea salt", "kosher salt",
    # pepper
    "black pepper", "white pepper", "ground pepper", "pepper",
    # oils
    "vegetable oil", "canola oil", "olive oil", "extra virgin olive oil",
    "oil", "cooking oil",
    # vinegar
    "white vinegar", "apple cider vinegar", "red wine vinegar", "vinegar",
    # water
    "water",
}

INGREDIENT_MODIFIERS: set[str] = {
    "fresh", "dried", "ground", "chopped", "minced", "sliced", "diced",
    "crushed", "large", "small", "medium", "whole", "boneless", "skinless",
    "organic", "frozen", "canned", "raw", "cooked", "shredded", "grated",
    "melted", "softened", "packed", "finely", "roughly", "thinly", "thick",
    "thin", "ripe", "firm", "extra", "plain", "unsalted", "salted",
    "unsweetened", "sweetened", "light", "dark", "low-fat", "full-fat",
    "reduced-fat", "lean", "trimmed", "peeled", "deveined", "pitted",
    "toasted", "roasted", "smoked", "pickled", "marinated",
}

# ---------------------------------------------------------------------------
# Generic swap table (used as last resort when user's own ingredients don't
# cover a category). For card-level swaps we now prefer _find_user_swap() first.
# ---------------------------------------------------------------------------
COMMON_SWAPS: dict[str, str] = {
    "chicken": "tofu or turkey",
    "chicken breast": "tofu or turkey",
    "chicken thigh": "tofu or turkey",
    "chicken thighs": "tofu or turkey",
    "beef": "mushrooms or turkey",
    "ground beef": "ground turkey or lentils",
    "steak": "portobello mushroom",
    "pork": "chicken or tofu",
    "pork chops": "chicken breast",
    "bacon": "turkey bacon or tempeh",
    "sausage": "turkey sausage",
    "shrimp": "chicken or tofu",
    "salmon": "chicken or cod",
    "fish": "chicken or tofu",
    "tuna": "chickpeas",
    "lamb": "beef or mushrooms",
    "taco shell": "tortilla or lettuce wrap",
    "taco shells": "tortillas or lettuce wraps",
    "tortilla": "lettuce wrap or flatbread",
    "tortillas": "lettuce wraps or flatbread",
    "pasta": "rice or zucchini noodles",
    "spaghetti": "rice noodles or zucchini",
    "noodles": "rice noodles or zucchini",
    "rice": "quinoa or cauliflower rice",
    "bread": "tortilla or lettuce wrap",
    "bun": "lettuce wrap",
    "buns": "lettuce wraps",
    "cream": "coconut cream",
    "heavy cream": "coconut cream",
    "sour cream": "greek yogurt",
    "cream cheese": "greek yogurt",
    "milk": "oat or almond milk",
    "cheese": "nutritional yeast",
    "cheddar cheese": "vegan cheddar",
    "mozzarella": "vegan mozzarella",
    "parmesan": "nutritional yeast",
    "yogurt": "coconut yogurt",
    "tofu": "chicken or paneer",
    "tempeh": "tofu or chickpeas",
    "potato": "sweet potato or cauliflower",
    "potatoes": "sweet potatoes",
    "coconut milk": "oat milk or almond milk",
}

# ---------------------------------------------------------------------------
# Swap category groups — ingredients in the same category can substitute for
# each other.  Used to find swaps from the USER's actual ingredients.
# ---------------------------------------------------------------------------
_SWAP_CATEGORIES: dict[str, set[str]] = {
    "protein": {
        "chicken", "chicken breast", "chicken thigh", "chicken thighs",
        "chicken leg", "chicken drumstick", "chicken tenders",
        "beef", "ground beef", "steak", "sirloin", "flank steak",
        "skirt steak", "ribeye",
        "pork", "pork chops", "pork loin", "pork tenderloin",
        "pork shoulder", "ground pork", "pork belly",
        "turkey", "ground turkey",
        "lamb", "ground lamb",
        "shrimp", "prawns", "salmon", "fish", "cod", "tilapia", "tuna",
        "tofu", "tempeh", "seitan",
        "sausage", "bacon", "ham",
    },
    "starch": {
        "pasta", "spaghetti", "linguine", "fettuccine", "penne", "rigatoni",
        "rotini", "fusilli", "farfalle", "macaroni", "ziti", "orzo",
        "rice", "white rice", "brown rice", "jasmine rice", "basmati rice",
        "noodles", "egg noodles", "ramen noodles", "udon noodles",
        "rice noodles", "lo mein noodles", "soba noodles",
        "potato", "potatoes", "sweet potato", "sweet potatoes",
        "bread", "tortilla", "tortillas", "naan", "pita", "flatbread",
        "bun", "buns", "rolls",
        "quinoa", "couscous", "bulgur",
    },
    "dairy": {
        "milk", "whole milk", "cream", "heavy cream", "half and half",
        "sour cream", "yogurt", "greek yogurt",
        "cheese", "cheddar", "mozzarella", "parmesan", "feta",
        "cream cheese", "ricotta", "butter",
        "coconut milk", "oat milk", "almond milk",
    },
    "allium": {
        "onion", "yellow onion", "white onion", "red onion",
        "shallot", "shallots", "green onion", "green onions",
        "scallion", "scallions", "leek", "leeks",
    },
    "acid": {
        "lemon", "lemon juice", "lime", "lime juice",
        "vinegar", "white vinegar", "red wine vinegar", "apple cider vinegar",
        "rice vinegar", "balsamic vinegar",
    },
}

# Reverse lookup: ingredient → category name
_INGREDIENT_TO_SWAP_CATEGORY: dict[str, str] = {}
for _cat_name, _cat_members in _SWAP_CATEGORIES.items():
    for _m in _cat_members:
        _INGREDIENT_TO_SWAP_CATEGORY[_m] = _cat_name


def _find_user_swap(
    missing_ingredient: str,
    user_ingredients: list["IngredientItem"],
    available_tokens: set[str],
) -> Optional[str]:
    """
    Given a missing recipe ingredient, see if the user has something in the
    same swap category. Returns the user ingredient name (e.g. 'beef') or
    None if no category match found.
    """
    lower = missing_ingredient.lower().strip()
    cat = _INGREDIENT_TO_SWAP_CATEGORY.get(lower)
    if not cat:
        # Strip modifiers and retry
        stripped = " ".join(t for t in lower.split() if t not in INGREDIENT_MODIFIERS)
        cat = _INGREDIENT_TO_SWAP_CATEGORY.get(stripped)
    if not cat:
        return None

    # Find the first user ingredient that is in the same category
    category_members = _SWAP_CATEGORIES[cat]
    for ing in user_ingredients:
        user_lower = ing.name.lower().strip()
        if user_lower == lower:
            continue  # same ingredient, not a swap
        if user_lower in category_members:
            return ing.name
        # Also check stripped version
        user_stripped = " ".join(t for t in user_lower.split() if t not in INGREDIENT_MODIFIERS)
        if user_stripped in category_members:
            return ing.name
    return None

# ── Ingredient equivalence families ────────────────────────────────────────
# Items in the same family are considered interchangeable for the purpose of
# card-level ingredient matching.  If the user's input contains ANY member
# of a family, a recipe ingredient that is ALSO in that family counts as
# "have it".  This is intentionally broad (pasta shapes are all the same,
# dairy milks are all the same, etc.).
_EQUIVALENCE_FAMILIES: list[set[str]] = [
    # Pasta (all shapes interchangeable)
    {
        "pasta", "spaghetti", "linguine", "fettuccine", "penne", "rigatoni",
        "rotini", "fusilli", "farfalle", "macaroni", "ziti", "orzo",
        "tagliatelle", "pappardelle", "bucatini", "angel hair",
        "elbow macaroni", "cavatappi", "orecchiette", "shells",
        "egg noodles", "noodles", "ramen noodles", "udon noodles",
        "rice noodles", "lo mein noodles", "soba noodles",
    },
    # Milk / cream family
    {
        "milk", "whole milk", "2% milk", "skim milk", "low-fat milk",
        "cream", "heavy cream", "heavy whipping cream", "whipping cream",
        "half and half", "half-and-half", "light cream",
        "evaporated milk", "coconut milk", "oat milk", "almond milk",
        "soy milk", "plant milk",
    },
    # Rice family
    {
        "rice", "white rice", "brown rice", "jasmine rice", "basmati rice",
        "long grain rice", "short grain rice", "sushi rice", "arborio rice",
        "wild rice", "instant rice",
    },
    # Chicken family
    {
        "chicken", "chicken breast", "chicken thigh", "chicken thighs",
        "chicken leg", "chicken legs", "chicken drumstick", "chicken drumsticks",
        "chicken wing", "chicken wings", "chicken tender", "chicken tenders",
        "rotisserie chicken", "boneless chicken",
    },
    # Beef family
    {
        "beef", "ground beef", "steak", "beef stew meat", "chuck roast",
        "sirloin", "flank steak", "skirt steak", "ribeye", "beef chuck",
        "stewing beef",
    },
    # Pork family
    {
        "pork", "pork chops", "pork loin", "pork tenderloin", "pork shoulder",
        "ground pork", "pork belly",
    },
    # Cheese family
    {
        "cheese", "cheddar cheese", "cheddar", "mozzarella", "mozzarella cheese",
        "parmesan", "parmesan cheese", "swiss cheese", "provolone",
        "monterey jack", "colby jack", "pepper jack", "american cheese",
        "cream cheese", "gouda", "gruyere", "feta", "feta cheese",
        "ricotta", "ricotta cheese", "cottage cheese",
    },
    # Onion family
    {
        "onion", "onions", "yellow onion", "white onion", "red onion",
        "sweet onion", "shallot", "shallots", "green onion", "green onions",
        "scallion", "scallions", "spring onion", "spring onions",
    },
    # Potato family
    {
        "potato", "potatoes", "russet potato", "russet potatoes",
        "yukon gold potato", "yukon gold potatoes", "red potato",
        "red potatoes", "sweet potato", "sweet potatoes", "baby potatoes",
        "fingerling potatoes", "new potatoes",
    },
    # Tomato family (canned/fresh interchangeable in cooking)
    {
        "tomato", "tomatoes", "cherry tomatoes", "grape tomatoes",
        "roma tomatoes", "plum tomatoes", "canned tomatoes",
        "diced tomatoes", "crushed tomatoes", "tomato sauce",
        "tomato paste", "tomato puree", "stewed tomatoes",
    },
    # Bread family
    {
        "bread", "white bread", "wheat bread", "whole wheat bread",
        "sourdough bread", "sandwich bread", "french bread", "italian bread",
        "ciabatta", "baguette", "rolls", "dinner rolls", "hamburger buns",
        "hot dog buns", "buns", "pita", "pita bread", "naan",
        "flatbread", "tortilla", "tortillas", "flour tortilla",
        "flour tortillas", "corn tortilla", "corn tortillas",
        "taco shell", "taco shells",
    },
    # Pepper family (bell peppers)
    {
        "bell pepper", "bell peppers", "green bell pepper", "red bell pepper",
        "yellow bell pepper", "orange bell pepper", "green pepper",
        "red pepper", "sweet pepper",
    },
    # Yogurt family
    {
        "yogurt", "greek yogurt", "plain yogurt", "vanilla yogurt",
        "sour cream",
    },
    # Lemon/lime acid interchangeable
    {
        "lemon", "lemons", "lemon juice", "lime", "limes", "lime juice",
    },
    # Garlic forms
    {
        "garlic", "garlic clove", "garlic cloves", "minced garlic",
        "fresh garlic", "crushed garlic",
    },
    # Butter
    {
        "butter", "unsalted butter", "salted butter",
    },
    # Egg
    {
        "egg", "eggs", "large egg", "large eggs",
    },
    # Sugar
    {
        "sugar", "white sugar", "granulated sugar", "cane sugar",
    },
    # Flour
    {
        "flour", "all-purpose flour", "all purpose flour", "ap flour",
        "plain flour", "whole wheat flour", "wheat flour",
    },
    # Soy sauce
    {
        "soy sauce", "low sodium soy sauce", "light soy sauce",
        "dark soy sauce", "tamari", "coconut aminos",
    },
]

# Build a lookup: ingredient_name → family_index for fast equivalence checks
_INGREDIENT_TO_FAMILY: dict[str, int] = {}
for _fam_idx, _family in enumerate(_EQUIVALENCE_FAMILIES):
    for _member in _family:
        _INGREDIENT_TO_FAMILY[_member] = _fam_idx


def _build_user_family_set(available_ingredients: list["IngredientItem"]) -> set[int]:
    """Return set of family indices the user's ingredients belong to."""
    families: set[int] = set()
    for ing in available_ingredients:
        lower = ing.name.lower().strip()
        if lower in _INGREDIENT_TO_FAMILY:
            families.add(_INGREDIENT_TO_FAMILY[lower])
        # Also check with modifiers stripped
        stripped = " ".join(t for t in lower.split() if t not in INGREDIENT_MODIFIERS)
        if stripped in _INGREDIENT_TO_FAMILY:
            families.add(_INGREDIENT_TO_FAMILY[stripped])
    return families


def _user_has_equivalent(recipe_ingredient_name: str, user_families: set[int]) -> bool:
    """Return True if the recipe ingredient belongs to a family the user covers."""
    lower = recipe_ingredient_name.lower().strip()
    fam = _INGREDIENT_TO_FAMILY.get(lower)
    if fam is not None and fam in user_families:
        return True
    # Check with modifiers stripped
    stripped = " ".join(t for t in lower.split() if t not in INGREDIENT_MODIFIERS)
    fam = _INGREDIENT_TO_FAMILY.get(stripped)
    if fam is not None and fam in user_families:
        return True
    return False


def _normalize_token(token: str) -> str:
    """Rough singularization for ingredient token matching."""
    if len(token) <= 2:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        base = token[:-2]
        if base.endswith(("s", "x", "z", "ch", "sh")):
            return base
        return token[:-1]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _tokenize(name: str) -> set[str]:
    """Tokenize, strip modifiers, and normalize an ingredient name."""
    raw = set(name.lower().replace("-", " ").split())
    meaningful = raw - INGREDIENT_MODIFIERS
    tokens = meaningful if meaningful else raw
    return {_normalize_token(t) for t in tokens}


def _is_pantry_staple(name: str) -> bool:
    """Return True if *name* is a common pantry staple most people already have."""
    lower = name.lower().strip()
    if lower in PANTRY_STAPLES:
        return True
    # Try with modifiers stripped (e.g. "freshly ground pepper" → "pepper")
    stripped = " ".join(t for t in lower.split() if t not in INGREDIENT_MODIFIERS)
    return stripped in PANTRY_STAPLES


def _build_available_token_set(available_ingredients: list[IngredientItem]) -> set[str]:
    """Flat set of normalised tokens from all available ingredients."""
    tokens: set[str] = set()
    for ing in available_ingredients:
        tokens.update(_tokenize(ing.name))
    return tokens


def _fuzzy_ingredient_match(recipe_name: str, available_tokens: set[str]) -> bool:
    """True if any core token of *recipe_name* appears in *available_tokens*."""
    return bool(_tokenize(recipe_name) & available_tokens)


def _get_swap(name: str) -> Optional[str]:
    """Look up common substitution for a missing ingredient (generic, not user-aware)."""
    lower = name.lower().strip()
    if lower in COMMON_SWAPS:
        return COMMON_SWAPS[lower]
    # Fuzzy token lookup
    tokens = _tokenize(lower)
    for key, val in COMMON_SWAPS.items():
        if _tokenize(key) & tokens:
            return val
    return None


def _get_user_aware_swap(
    name: str,
    context: SessionContextRequest,
    available_tokens: set[str],
) -> Optional[str]:
    """
    Try to find a swap from the user's OWN ingredients first.
    Falls back to the generic COMMON_SWAPS table.
    Returns a short string like 'use beef instead' or 'try oat milk'.
    """
    user_swap = _find_user_swap(name, context.available_ingredients, available_tokens)
    if user_swap:
        return f"use {user_swap} instead"
    # Fallback to generic
    generic = _get_swap(name)
    return generic


def compute_ingredient_match(
    recipe: dict,
    context: SessionContextRequest,
    available_tokens: Optional[set[str]] = None,
) -> dict:
    """
    Analyse how well a user's available ingredients cover a recipe.

    Matching hierarchy for each recipe ingredient:
      1. Pantry staple → auto-matched
      2. Fuzzy token match against user's ingredients → matched
      3. Equivalence family match (e.g. user has "pasta", recipe needs
         "fettuccine") → matched (counts as "have it")
      4. Otherwise → unmatched

    Returns dict with:
      ingredient_match_pct, matched_ingredient_count, total_ingredient_count,
      missing_key_ingredients, swap_suggestions
    """
    if available_tokens is None:
        available_tokens = _build_available_token_set(context.available_ingredients)

    user_families = _build_user_family_set(context.available_ingredients)

    recipe_ingredients = recipe.get("ingredients") or []
    matched: list[str] = []
    unmatched: list[str] = []

    for ing in recipe_ingredients:
        name = (ing.get("name") or "").lower().strip()
        if not name:
            continue
        if _is_pantry_staple(name):
            matched.append(name)
            continue
        if _fuzzy_ingredient_match(name, available_tokens):
            matched.append(name)
            continue
        # Check equivalence families — user has pasta, recipe needs fettuccine
        if _user_has_equivalent(name, user_families):
            matched.append(name)
            continue
        unmatched.append(name)

    total = len(matched) + len(unmatched)
    match_pct = round((len(matched) / total * 100) if total > 0 else 100, 1)

    # Key ingredients: non-staples in first 8 positions OR whose tokens appear
    # in the recipe title (e.g. "chicken" in "Easy Chicken Curry").
    title_tokens = _tokenize(recipe.get("title") or "")
    key_ingredients: list[str] = []
    non_staple_idx = 0
    for ing in recipe_ingredients:
        name = (ing.get("name") or "").lower().strip()
        if not name or _is_pantry_staple(name):
            continue
        name_tokens = _tokenize(name)
        is_title_ingredient = bool(name_tokens & title_tokens)
        if non_staple_idx < 5 or is_title_ingredient:
            key_ingredients.append(name)
        non_staple_idx += 1

    unmatched_set = set(unmatched)
    missing_key = [n for n in key_ingredients if n in unmatched_set]

    # --- User-available swap matching ---
    # If a missing ingredient has a swap the user actually owns (same category),
    # count it as matched and record the swap for the card UI.
    swap_suggestions: list[dict] = []
    swap_recovered: list[str] = []  # ingredients recovered via user swap
    for name in missing_key:
        user_swap = _find_user_swap(name, context.available_ingredients, available_tokens)
        if user_swap:
            # User can substitute — count as matched
            swap_recovered.append(name)
            swap_suggestions.append({"ingredient": name, "swap": f"use {user_swap} instead"})
        else:
            # Fall back to generic swap hint
            generic = _get_swap(name)
            swap_suggestions.append({"ingredient": name, "swap": generic})

    # Adjust counts: swap-recovered ingredients count as "have it"
    final_matched = len(matched) + len(swap_recovered)
    final_total = total
    final_pct = round((final_matched / final_total * 100) if final_total > 0 else 100, 1)

    # Remaining truly missing keys (not recovered by user swap)
    truly_missing = [n for n in missing_key if n not in set(swap_recovered)]

    return {
        "ingredient_match_pct": final_pct,
        "matched_ingredient_count": final_matched,
        "total_ingredient_count": final_total,
        "missing_key_ingredients": truly_missing[:5],
        "swap_suggestions": swap_suggestions[:5],
    }


def score_rules(
    recipe: dict,
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    cuisine_preferences: list[str],
    cooking_equipment: list[str],
    match_info: dict | None = None,
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
            # Crude keyword check against ingredient names
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

    # --- Ingredient overlap (0-40 pts) + key-ingredient penalty ---
    if match_info is None:
        match_info = compute_ingredient_match(recipe, context)
    match_pct = match_info.get("ingredient_match_pct", 0)
    score += (match_pct / 100.0) * 40.0
    missing_key_count = len(match_info.get("missing_key_ingredients", []))
    score -= min(36.0, missing_key_count * 12.0)

    # --- Hard filter: title-defining ingredient ---
    # If the recipe title names a specific main ingredient (e.g. "chicken" in
    # "Chicken Fajitas", "egg" in "Scrambled Eggs") and the user has NO way to
    # obtain it (not in pantry, not in equivalence family, no same-category swap),
    # then reject the recipe entirely — it makes no sense to recommend it.
    title = (recipe.get("title") or "").lower()
    title_tokens = _tokenize(title)
    available_tokens_local = _build_available_token_set(context.available_ingredients)
    user_families = _build_user_family_set(context.available_ingredients)

    # Identify ingredients that appear in the recipe title
    recipe_ingredients = recipe.get("ingredients") or []
    for ing in recipe_ingredients:
        ing_name = (ing.get("name") or "").lower().strip()
        if not ing_name or _is_pantry_staple(ing_name):
            continue
        ing_tokens = _tokenize(ing_name)
        # Is this ingredient mentioned in the title?
        if not (ing_tokens & title_tokens):
            continue
        # Title ingredient — check if user can access it at all
        has_direct = _fuzzy_ingredient_match(ing_name, available_tokens_local)
        has_family = _user_has_equivalent(ing_name, user_families)
        has_swap = _find_user_swap(ing_name, context.available_ingredients, available_tokens_local) is not None
        if not (has_direct or has_family or has_swap):
            logger.debug(
                "Hard-filter: recipe '%s' title ingredient '%s' unavailable (no match/swap)",
                recipe.get("title", ""), ing_name,
            )
            return float("-inf")
    # Kept intentionally small so urgency gently nudges rather than dominates.
    urgent_names = {
        i.name.lower() for i in context.available_ingredients
        if i.urgency is not None and i.urgency <= 3
    }
    if urgent_names:
        urgent_tokens: set[str] = set()
        for uname in urgent_names:
            urgent_tokens.update(_tokenize(uname))
        recipe_ing_names = [
            (i.get("name") or "").lower()
            for i in (recipe.get("ingredients") or [])
        ]
        urgency_hits = sum(
            1 for rn in recipe_ing_names if _tokenize(rn) & urgent_tokens
        )
        score += min(10.0, urgency_hits * 5.0)

    # --- Cuisine affinity (0-15 pts) ---
    if cuisine_preferences:
        recipe_cuisine = (recipe.get("cuisine") or "").lower()
        if any(recipe_cuisine == p.lower() for p in cuisine_preferences):
            score += 15.0

    # --- Equipment match (hard penalty when user is missing required equipment) ---
    needed_equipment = set(recipe.get("cooking_equipment") or [])

    # Infer equipment from recipe title/ingredients when not explicitly listed
    title_lower = (recipe.get("title") or "").lower()
    all_ing_text = " ".join(i.get("name", "") for i in (recipe.get("ingredients") or [])).lower()
    all_inst_text = " ".join(
        (s.get("text") or s.get("step_text") or "")
        for s in (recipe.get("instructions") or [])
    ).lower()
    combined_text = f"{title_lower} {all_ing_text} {all_inst_text}"

    # Equipment inference rules
    _EQUIPMENT_INFER = {
        # Only infer blender when a recipe clearly cannot be made without one.
        # "blend until smooth" / "puree" / "purée" are too broad — pasta sauces
        # and many dishes use these phrases but can be made with a whisk or fork.
        "blender": ["smoothie", "in a blender", "transfer to blender", "using a blender", "blender"],
        "food processor": ["food processor", "pulse until"],
        "grill": ["grilled", "grill marks", "on the grill", "charcoal"],
        "slow cooker": ["slow cooker", "crockpot", "crock pot", "crock-pot"],
        "instant pot": ["instant pot", "pressure cook"],
        "air fryer": ["air fryer", "air fry", "air-fry"],
        "deep fryer": ["deep fry", "deep-fry", "deep fryer"],
        # Stir-frying in a regular skillet/pan is completely normal — only infer
        # wok requirement when the recipe text explicitly calls for a wok.
        "wok": ["wok"],
    }
    for equip, keywords in _EQUIPMENT_INFER.items():
        if any(kw in combined_text for kw in keywords):
            needed_equipment.add(equip)

    if not needed_equipment:
        score += 10.0  # no special equipment needed = full points
    elif cooking_equipment:
        have = set(e.lower() for e in cooking_equipment)
        needed = set(e.lower() for e in needed_equipment)
        if needed.issubset(have):
            score += 10.0
        else:
            missing = needed - have
            # Major equipment mismatch = hard filter out
            major_equipment = {"oven", "grill", "bbq", "air fryer", "instant pot",
                               "slow cooker", "pressure cooker", "smoker", "wok",
                               "deep fryer", "blender", "food processor"}
            missing_major = missing & major_equipment
            if missing_major:
                logger.debug("Hard-filter: recipe '%s' needs %s which user lacks",
                             recipe.get("title", ""), missing_major)
                return float("-inf")
            # Minor equipment missing (e.g. whisk, spatula) — penalty but not exclusion
            score -= 10.0 * (len(missing) / len(needed))

    # --- Recipe rating (0-5 pts) ---
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
    available_tokens = _build_available_token_set(context.available_ingredients)
    scored = []
    for recipe in recipes:
        match_info = compute_ingredient_match(recipe, context, available_tokens)
        rule_score = score_rules(recipe, context, dietary_restrictions, cuisine_preferences, cooking_equipment, match_info)
        if not math.isinf(rule_score):
            scored.append({**recipe, "score": rule_score, **match_info})

    scored.sort(key=lambda r: (r.get("ingredient_match_pct", 0), r["score"]), reverse=True)
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

        raw = await ollama_chat(
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1024,
            temperature=0.2,
            timeout=LLM_TIMEOUT_SECONDS,
            think=False,
        )

        logger.debug("Re-ranker raw response (first 500 chars): %s", raw[:500])
        clean = _extract_json(raw)
        if not clean.strip():
            raise ValueError("Re-ranker returned empty content after extraction")
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
