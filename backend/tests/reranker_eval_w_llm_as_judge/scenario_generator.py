"""
Generates diverse test scenarios for the eval pipeline.

Each scenario is a realistic user session with:
  - A user preference profile (cuisines, dietary, equipment, health goal)
  - A session context (meal type, time, occasion, pantry with urgency signals)
  - A human-readable persona description

Two modes:
  1. LLM mode  — calls Ollama to generate N creative scenarios
  2. Static mode — returns a hardcoded set of 20 hand-crafted scenarios
     (use when Ollama is unavailable or you want deterministic tests)

Run standalone to preview generated scenarios:
    cd backend && python -m tests.eval.scenario_generator --n 5
"""

import asyncio
import json
import os
import sys
import argparse

# ── LLM config ────────────────────────────────────────────────────────────────
_DEFAULT_OLLAMA_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
_DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen3:4b")

_SCENARIO_SYSTEM_PROMPT = """You are a test data generator for a recipe recommendation app.
Generate diverse, realistic user scenarios. Each scenario must have a distinct persona —
vary cuisines, dietary needs, equipment, time constraints, pantry contents, and occasions.

IMPORTANT RULES:
- available_ingredients must be realistic pantry items, not invented or brand-name items
- urgency values (days until spoilage) should only appear on perishable items: meat, fish,
  dairy, fresh produce. Set urgency=null for shelf-stable items.
- cuisine_preferences must be lowercase strings from this list:
  italian, mexican, chinese, japanese, indian, thai, korean, mediterranean, american,
  french, middle eastern, vietnamese, greek, caribbean, african
- dietary_restrictions must be from: gluten-free, vegan, vegetarian, dairy-free,
  nut-free, soy-free, egg-free, pescatarian
- cooking_equipment must be from: stove, oven, microwave, blender, air fryer,
  instant pot, slow cooker, grill (always include "stove")
- health_goal must be one of: weight-loss, muscle-gain, maintenance, none
- meal_type must be one of: breakfast, lunch, dinner
- occasion is optional (null or a brief string like "date night", "meal prep", "casual weeknight")

Output ONLY a valid JSON array. No explanation."""

_SCENARIO_USER_PROMPT = """Generate {n} diverse test scenarios. Each scenario is a JSON object with exactly this schema:

{{
  "persona_description": "brief human-readable description of this user and context",
  "user_preferences": {{
    "cuisine_preferences": ["cuisine1", "cuisine2"],
    "dietary_restrictions": [],
    "health_goal": "maintenance",
    "cooking_equipment": ["stove"]
  }},
  "session_context": {{
    "meal_type": "dinner",
    "serving_count": 2,
    "available_time_minutes": 45,
    "occasion": null,
    "available_ingredients": [
      {{"name": "chicken breast", "quantity": 2.0, "unit": "pieces", "urgency": 2}},
      {{"name": "rice", "quantity": 1.0, "unit": "cups", "urgency": null}}
    ]
  }}
}}

Make sure scenarios cover a wide range:
- At least 2 vegan scenarios
- At least 2 gluten-free scenarios
- At least 1 nut-free scenario
- At least 3 scenarios with urgent ingredients (urgency <= 3)
- At least 2 time-constrained scenarios (available_time_minutes <= 25)
- At least 1 long-cook scenario (available_time_minutes >= 60)
- Varied cuisine preferences across all major regions
- Varied equipment (some with only stove, some with oven, some with air fryer)
- Varied health goals
- Varied occasions (some null, some specific)

Return ONLY a valid JSON array of {n} scenario objects."""


async def generate_scenarios_llm(
    n: int,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    model: str = _DEFAULT_MODEL,
) -> list[dict]:
    """Generate N scenarios using the LLM."""
    # Import here to avoid database init at module import time
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
    from app.services.inference_client import ollama_chat

    messages = [
        {"role": "system", "content": _SCENARIO_SYSTEM_PROMPT},
        {"role": "user", "content": _SCENARIO_USER_PROMPT.format(n=n)},
    ]

    print(f"  [scenario_generator] Generating {n} scenarios via LLM...", flush=True)
    raw = await ollama_chat(
        base_url=ollama_url,
        model=model,
        messages=messages,
        max_tokens=8192,
        temperature=0.9,  # High temp = more creative variety
        think=False,
        priority="normal",
    )

    # Extract JSON array from response
    raw = raw.strip()
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError(f"LLM did not return a JSON array. Got: {raw[:200]}")

    scenarios = json.loads(raw[start:end])
    if not isinstance(scenarios, list):
        raise ValueError("Expected a JSON array of scenarios")

    # Validate and normalise each scenario
    validated = []
    for i, s in enumerate(scenarios):
        try:
            validated.append(_validate_scenario(s, i + 1))
        except Exception as e:
            print(f"  [scenario_generator] WARNING: scenario {i+1} invalid ({e}), skipping")

    print(f"  [scenario_generator] Got {len(validated)} valid scenarios")
    return validated


def _validate_scenario(s: dict, idx: int) -> dict:
    """Normalise and validate a single scenario dict."""
    assert isinstance(s.get("persona_description"), str), "missing persona_description"
    prefs = s.get("user_preferences", {})
    ctx = s.get("session_context", {})

    # Normalise cuisines to lowercase
    prefs["cuisine_preferences"] = [c.lower() for c in prefs.get("cuisine_preferences", [])]

    # Ensure stove is always in equipment
    equip = prefs.get("cooking_equipment", [])
    if "stove" not in equip:
        equip = ["stove"] + equip
    prefs["cooking_equipment"] = equip

    # Normalise ingredients
    for ing in ctx.get("available_ingredients", []):
        ing["urgency"] = ing.get("urgency")  # None is valid
        ing.setdefault("quantity", 1.0)
        ing.setdefault("unit", "pieces")

    s["id"] = idx
    s["user_preferences"] = prefs
    s["session_context"] = ctx
    return s


def get_static_scenarios() -> list[dict]:
    """
    20 hand-crafted scenarios for deterministic testing.
    Covers a wide range of constraints and preferences.
    """
    return [
        {
            "id": 1,
            "persona_description": "Busy weeknight home cook, Italian and Mexican fan, has chicken expiring soon",
            "user_preferences": {
                "cuisine_preferences": ["italian", "mexican"],
                "dietary_restrictions": [],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 40,
                "occasion": None,
                "available_ingredients": [
                    {"name": "chicken breast", "quantity": 2.0, "unit": "pieces", "urgency": 2},
                    {"name": "garlic", "quantity": 5.0, "unit": "cloves", "urgency": None},
                    {"name": "olive oil", "quantity": 1.0, "unit": "cup", "urgency": None},
                    {"name": "pasta", "quantity": 200.0, "unit": "g", "urgency": None},
                    {"name": "canned tomatoes", "quantity": 1.0, "unit": "can", "urgency": None},
                    {"name": "parmesan cheese", "quantity": 0.5, "unit": "cup", "urgency": 5},
                ],
            },
        },
        {
            "id": 2,
            "persona_description": "Vegan athlete focused on muscle gain, prefers Asian flavors, has tofu and lots of vegetables",
            "user_preferences": {
                "cuisine_preferences": ["chinese", "thai", "japanese"],
                "dietary_restrictions": ["vegan"],
                "health_goal": "muscle-gain",
                "cooking_equipment": ["stove", "air fryer"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 1,
                "available_time_minutes": 35,
                "occasion": None,
                "available_ingredients": [
                    {"name": "firm tofu", "quantity": 400.0, "unit": "g", "urgency": 3},
                    {"name": "broccoli", "quantity": 2.0, "unit": "cups", "urgency": 2},
                    {"name": "rice", "quantity": 2.0, "unit": "cups", "urgency": None},
                    {"name": "soy sauce", "quantity": 1.0, "unit": "cup", "urgency": None},
                    {"name": "sesame oil", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "garlic", "quantity": 4.0, "unit": "cloves", "urgency": None},
                    {"name": "ginger", "quantity": 1.0, "unit": "piece", "urgency": 5},
                ],
            },
        },
        {
            "id": 3,
            "persona_description": "Gluten-free family dinner, Indian food lover, has salmon about to expire, oven available",
            "user_preferences": {
                "cuisine_preferences": ["indian", "mediterranean"],
                "dietary_restrictions": ["gluten-free"],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 4,
                "available_time_minutes": 50,
                "occasion": "family dinner",
                "available_ingredients": [
                    {"name": "salmon fillet", "quantity": 4.0, "unit": "pieces", "urgency": 1},
                    {"name": "onion", "quantity": 2.0, "unit": "pieces", "urgency": None},
                    {"name": "garlic", "quantity": 5.0, "unit": "cloves", "urgency": None},
                    {"name": "ginger", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "cumin", "quantity": 1.0, "unit": "tsp", "urgency": None},
                    {"name": "turmeric", "quantity": 0.5, "unit": "tsp", "urgency": None},
                    {"name": "rice", "quantity": 2.0, "unit": "cups", "urgency": None},
                    {"name": "yogurt", "quantity": 1.0, "unit": "cup", "urgency": 3},
                ],
            },
        },
        {
            "id": 4,
            "persona_description": "Super time-constrained, only 20 minutes, minimal pantry, no dietary restrictions",
            "user_preferences": {
                "cuisine_preferences": ["american", "italian"],
                "dietary_restrictions": [],
                "health_goal": "none",
                "cooking_equipment": ["stove"],
            },
            "session_context": {
                "meal_type": "lunch",
                "serving_count": 1,
                "available_time_minutes": 20,
                "occasion": None,
                "available_ingredients": [
                    {"name": "eggs", "quantity": 3.0, "unit": "pieces", "urgency": None},
                    {"name": "pasta", "quantity": 100.0, "unit": "g", "urgency": None},
                    {"name": "garlic", "quantity": 2.0, "unit": "cloves", "urgency": None},
                    {"name": "olive oil", "quantity": 0.5, "unit": "cup", "urgency": None},
                ],
            },
        },
        {
            "id": 5,
            "persona_description": "Nut-free due to severe allergy, loves Korean and Japanese food, has beef expiring",
            "user_preferences": {
                "cuisine_preferences": ["korean", "japanese"],
                "dietary_restrictions": ["nut-free"],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 45,
                "occasion": None,
                "available_ingredients": [
                    {"name": "ground beef", "quantity": 400.0, "unit": "g", "urgency": 2},
                    {"name": "rice", "quantity": 2.0, "unit": "cups", "urgency": None},
                    {"name": "soy sauce", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "sesame oil", "quantity": 0.25, "unit": "cup", "urgency": None},
                    {"name": "garlic", "quantity": 3.0, "unit": "cloves", "urgency": None},
                    {"name": "ginger", "quantity": 1.0, "unit": "tsp", "urgency": None},
                    {"name": "scallions", "quantity": 4.0, "unit": "stalks", "urgency": 3},
                ],
            },
        },
        {
            "id": 6,
            "persona_description": "Vegan weight-loss journey, Mediterranean preference, large meal prep batch for 6 people",
            "user_preferences": {
                "cuisine_preferences": ["mediterranean", "middle eastern"],
                "dietary_restrictions": ["vegan"],
                "health_goal": "weight-loss",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 6,
                "available_time_minutes": 60,
                "occasion": "meal prep",
                "available_ingredients": [
                    {"name": "red lentils", "quantity": 2.0, "unit": "cups", "urgency": None},
                    {"name": "chickpeas", "quantity": 2.0, "unit": "cans", "urgency": None},
                    {"name": "spinach", "quantity": 4.0, "unit": "cups", "urgency": 2},
                    {"name": "canned tomatoes", "quantity": 2.0, "unit": "cans", "urgency": None},
                    {"name": "onion", "quantity": 2.0, "unit": "pieces", "urgency": None},
                    {"name": "garlic", "quantity": 6.0, "unit": "cloves", "urgency": None},
                    {"name": "cumin", "quantity": 2.0, "unit": "tsp", "urgency": None},
                    {"name": "olive oil", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "lemon", "quantity": 2.0, "unit": "pieces", "urgency": 5},
                ],
            },
        },
        {
            "id": 7,
            "persona_description": "Quick breakfast, vegetarian, just eggs and some basics, 15 minutes max",
            "user_preferences": {
                "cuisine_preferences": ["american", "mediterranean"],
                "dietary_restrictions": ["vegetarian"],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove"],
            },
            "session_context": {
                "meal_type": "breakfast",
                "serving_count": 2,
                "available_time_minutes": 15,
                "occasion": None,
                "available_ingredients": [
                    {"name": "eggs", "quantity": 6.0, "unit": "pieces", "urgency": None},
                    {"name": "tomato", "quantity": 2.0, "unit": "pieces", "urgency": 2},
                    {"name": "feta cheese", "quantity": 0.5, "unit": "cup", "urgency": 4},
                    {"name": "onion", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "olive oil", "quantity": 0.5, "unit": "cup", "urgency": None},
                ],
            },
        },
        {
            "id": 8,
            "persona_description": "Date night dinner, 60 min budget, Italian and French preference, has salmon and cream",
            "user_preferences": {
                "cuisine_preferences": ["italian", "french", "mediterranean"],
                "dietary_restrictions": [],
                "health_goal": "none",
                "cooking_equipment": ["stove", "oven", "blender"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 60,
                "occasion": "date night",
                "available_ingredients": [
                    {"name": "salmon fillet", "quantity": 2.0, "unit": "pieces", "urgency": 1},
                    {"name": "heavy cream", "quantity": 1.0, "unit": "cup", "urgency": 3},
                    {"name": "arborio rice", "quantity": 300.0, "unit": "g", "urgency": None},
                    {"name": "mushrooms", "quantity": 200.0, "unit": "g", "urgency": 2},
                    {"name": "white wine", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "butter", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "parmesan cheese", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "garlic", "quantity": 4.0, "unit": "cloves", "urgency": None},
                ],
            },
        },
        {
            "id": 9,
            "persona_description": "Meal prep Sunday, no specific dietary restrictions, American and Mexican, has ground beef and chicken",
            "user_preferences": {
                "cuisine_preferences": ["american", "mexican"],
                "dietary_restrictions": [],
                "health_goal": "muscle-gain",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 6,
                "available_time_minutes": 75,
                "occasion": "meal prep",
                "available_ingredients": [
                    {"name": "ground beef", "quantity": 800.0, "unit": "g", "urgency": 3},
                    {"name": "chicken breast", "quantity": 600.0, "unit": "g", "urgency": 3},
                    {"name": "rice", "quantity": 3.0, "unit": "cups", "urgency": None},
                    {"name": "black beans", "quantity": 2.0, "unit": "cans", "urgency": None},
                    {"name": "canned tomatoes", "quantity": 2.0, "unit": "cans", "urgency": None},
                    {"name": "onion", "quantity": 2.0, "unit": "pieces", "urgency": None},
                    {"name": "cumin", "quantity": 2.0, "unit": "tsp", "urgency": None},
                    {"name": "corn tortillas", "quantity": 12.0, "unit": "pieces", "urgency": None},
                ],
            },
        },
        {
            "id": 10,
            "persona_description": "Strict gluten-free vegan, Asian-only preference, only stove, tight 25-minute window",
            "user_preferences": {
                "cuisine_preferences": ["chinese", "thai", "vietnamese"],
                "dietary_restrictions": ["gluten-free", "vegan"],
                "health_goal": "weight-loss",
                "cooking_equipment": ["stove"],
            },
            "session_context": {
                "meal_type": "lunch",
                "serving_count": 1,
                "available_time_minutes": 25,
                "occasion": None,
                "available_ingredients": [
                    {"name": "firm tofu", "quantity": 200.0, "unit": "g", "urgency": 2},
                    {"name": "rice noodles", "quantity": 100.0, "unit": "g", "urgency": None},
                    {"name": "spinach", "quantity": 2.0, "unit": "cups", "urgency": 1},
                    {"name": "garlic", "quantity": 3.0, "unit": "cloves", "urgency": None},
                    {"name": "soy sauce", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "sesame oil", "quantity": 2.0, "unit": "tsp", "urgency": None},
                    {"name": "lime", "quantity": 1.0, "unit": "piece", "urgency": None},
                ],
            },
        },
        {
            "id": 11,
            "persona_description": "Pescatarian with dairy-free restriction, Mediterranean fan, shrimp expiring today",
            "user_preferences": {
                "cuisine_preferences": ["mediterranean", "greek"],
                "dietary_restrictions": ["dairy-free"],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 35,
                "occasion": None,
                "available_ingredients": [
                    {"name": "shrimp", "quantity": 300.0, "unit": "g", "urgency": 1},
                    {"name": "cherry tomatoes", "quantity": 1.0, "unit": "cup", "urgency": 3},
                    {"name": "zucchini", "quantity": 1.0, "unit": "piece", "urgency": 2},
                    {"name": "olive oil", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "garlic", "quantity": 3.0, "unit": "cloves", "urgency": None},
                    {"name": "lemon", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "pasta", "quantity": 200.0, "unit": "g", "urgency": None},
                ],
            },
        },
        {
            "id": 12,
            "persona_description": "Vegetarian student, very limited budget pantry, no special equipment, Indian food fan",
            "user_preferences": {
                "cuisine_preferences": ["indian", "middle eastern"],
                "dietary_restrictions": ["vegetarian"],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 1,
                "available_time_minutes": 45,
                "occasion": None,
                "available_ingredients": [
                    {"name": "red lentils", "quantity": 1.0, "unit": "cup", "urgency": None},
                    {"name": "onion", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "garlic", "quantity": 2.0, "unit": "cloves", "urgency": None},
                    {"name": "cumin", "quantity": 1.0, "unit": "tsp", "urgency": None},
                    {"name": "turmeric", "quantity": 0.5, "unit": "tsp", "urgency": None},
                    {"name": "canned tomatoes", "quantity": 1.0, "unit": "can", "urgency": None},
                    {"name": "rice", "quantity": 1.0, "unit": "cup", "urgency": None},
                ],
            },
        },
        {
            "id": 13,
            "persona_description": "Air fryer enthusiast, Thai and Korean cuisine preference, tofu and eggs, no dietary restrictions",
            "user_preferences": {
                "cuisine_preferences": ["thai", "korean", "japanese"],
                "dietary_restrictions": [],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove", "air fryer"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 40,
                "occasion": None,
                "available_ingredients": [
                    {"name": "firm tofu", "quantity": 400.0, "unit": "g", "urgency": 3},
                    {"name": "eggs", "quantity": 3.0, "unit": "pieces", "urgency": None},
                    {"name": "rice", "quantity": 2.0, "unit": "cups", "urgency": None},
                    {"name": "peanut butter", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "soy sauce", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "lime", "quantity": 2.0, "unit": "pieces", "urgency": None},
                    {"name": "cucumber", "quantity": 1.0, "unit": "piece", "urgency": 2},
                ],
            },
        },
        {
            "id": 14,
            "persona_description": "Slow cooker Sunday, family of 4, Mexican preference, pork shoulder to use",
            "user_preferences": {
                "cuisine_preferences": ["mexican", "american"],
                "dietary_restrictions": [],
                "health_goal": "none",
                "cooking_equipment": ["stove", "slow cooker", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 4,
                "available_time_minutes": 600,
                "occasion": "family dinner",
                "available_ingredients": [
                    {"name": "pork shoulder", "quantity": 1.5, "unit": "kg", "urgency": 2},
                    {"name": "onion", "quantity": 2.0, "unit": "pieces", "urgency": None},
                    {"name": "garlic", "quantity": 5.0, "unit": "cloves", "urgency": None},
                    {"name": "cumin", "quantity": 2.0, "unit": "tsp", "urgency": None},
                    {"name": "orange juice", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "corn tortillas", "quantity": 12.0, "unit": "pieces", "urgency": None},
                    {"name": "lime", "quantity": 2.0, "unit": "pieces", "urgency": None},
                ],
            },
        },
        {
            "id": 15,
            "persona_description": "Gluten-free fitness focused, lots of chicken and vegetables, only stove, American food",
            "user_preferences": {
                "cuisine_preferences": ["american", "mediterranean"],
                "dietary_restrictions": ["gluten-free"],
                "health_goal": "muscle-gain",
                "cooking_equipment": ["stove"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 30,
                "occasion": None,
                "available_ingredients": [
                    {"name": "chicken breast", "quantity": 3.0, "unit": "pieces", "urgency": 2},
                    {"name": "broccoli", "quantity": 2.0, "unit": "cups", "urgency": 2},
                    {"name": "bell pepper", "quantity": 2.0, "unit": "pieces", "urgency": 3},
                    {"name": "garlic", "quantity": 3.0, "unit": "cloves", "urgency": None},
                    {"name": "olive oil", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "lemon", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "rice", "quantity": 1.5, "unit": "cups", "urgency": None},
                ],
            },
        },
        {
            "id": 16,
            "persona_description": "Italian-obsessed cook with a well-stocked pantry, date night, oven + blender, no restrictions",
            "user_preferences": {
                "cuisine_preferences": ["italian", "french"],
                "dietary_restrictions": [],
                "health_goal": "none",
                "cooking_equipment": ["stove", "oven", "blender"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 55,
                "occasion": "date night",
                "available_ingredients": [
                    {"name": "arborio rice", "quantity": 300.0, "unit": "g", "urgency": None},
                    {"name": "mushrooms", "quantity": 250.0, "unit": "g", "urgency": 2},
                    {"name": "parmesan cheese", "quantity": 1.0, "unit": "cup", "urgency": None},
                    {"name": "white wine", "quantity": 1.0, "unit": "cup", "urgency": None},
                    {"name": "butter", "quantity": 4.0, "unit": "tbsp", "urgency": None},
                    {"name": "onion", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "garlic", "quantity": 4.0, "unit": "cloves", "urgency": None},
                    {"name": "chicken broth", "quantity": 4.0, "unit": "cups", "urgency": None},
                ],
            },
        },
        {
            "id": 17,
            "persona_description": "Vegan meal prep, large batch, no special equipment beyond stove, loves Vietnamese pho-style flavors",
            "user_preferences": {
                "cuisine_preferences": ["vietnamese", "thai", "chinese"],
                "dietary_restrictions": ["vegan"],
                "health_goal": "weight-loss",
                "cooking_equipment": ["stove"],
            },
            "session_context": {
                "meal_type": "lunch",
                "serving_count": 4,
                "available_time_minutes": 50,
                "occasion": "meal prep",
                "available_ingredients": [
                    {"name": "rice noodles", "quantity": 300.0, "unit": "g", "urgency": None},
                    {"name": "vegetable broth", "quantity": 6.0, "unit": "cups", "urgency": None},
                    {"name": "mushrooms", "quantity": 200.0, "unit": "g", "urgency": 2},
                    {"name": "bok choy", "quantity": 3.0, "unit": "pieces", "urgency": 2},
                    {"name": "ginger", "quantity": 2.0, "unit": "inches", "urgency": None},
                    {"name": "star anise", "quantity": 3.0, "unit": "pieces", "urgency": None},
                    {"name": "soy sauce", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "lime", "quantity": 3.0, "unit": "pieces", "urgency": None},
                ],
            },
        },
        {
            "id": 18,
            "persona_description": "Quick breakfast for two, vegetarian, blender available, mostly fridge leftovers",
            "user_preferences": {
                "cuisine_preferences": ["american"],
                "dietary_restrictions": ["vegetarian"],
                "health_goal": "maintenance",
                "cooking_equipment": ["stove", "blender"],
            },
            "session_context": {
                "meal_type": "breakfast",
                "serving_count": 2,
                "available_time_minutes": 15,
                "occasion": None,
                "available_ingredients": [
                    {"name": "frozen banana", "quantity": 2.0, "unit": "pieces", "urgency": None},
                    {"name": "frozen berries", "quantity": 2.0, "unit": "cups", "urgency": None},
                    {"name": "almond milk", "quantity": 1.0, "unit": "cup", "urgency": 3},
                    {"name": "granola", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "avocado", "quantity": 1.0, "unit": "piece", "urgency": 1},
                    {"name": "eggs", "quantity": 4.0, "unit": "pieces", "urgency": None},
                    {"name": "sourdough bread", "quantity": 4.0, "unit": "slices", "urgency": 2},
                ],
            },
        },
        {
            "id": 19,
            "persona_description": "Picky eater, American-only preference, no dietary restrictions, basic pantry, 30 minutes",
            "user_preferences": {
                "cuisine_preferences": ["american"],
                "dietary_restrictions": [],
                "health_goal": "none",
                "cooking_equipment": ["stove", "oven"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 2,
                "available_time_minutes": 30,
                "occasion": None,
                "available_ingredients": [
                    {"name": "chicken breast", "quantity": 2.0, "unit": "pieces", "urgency": 3},
                    {"name": "romaine lettuce", "quantity": 1.0, "unit": "head", "urgency": 2},
                    {"name": "parmesan cheese", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "caesar dressing", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "olive oil", "quantity": 2.0, "unit": "tbsp", "urgency": None},
                ],
            },
        },
        {
            "id": 20,
            "persona_description": "Korean BBQ night, grill available, beef and vegetables, no restrictions, weekend fun",
            "user_preferences": {
                "cuisine_preferences": ["korean", "japanese"],
                "dietary_restrictions": [],
                "health_goal": "none",
                "cooking_equipment": ["stove", "grill"],
            },
            "session_context": {
                "meal_type": "dinner",
                "serving_count": 4,
                "available_time_minutes": 50,
                "occasion": "casual party",
                "available_ingredients": [
                    {"name": "beef sirloin", "quantity": 600.0, "unit": "g", "urgency": 2},
                    {"name": "soy sauce", "quantity": 0.5, "unit": "cup", "urgency": None},
                    {"name": "sesame oil", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "garlic", "quantity": 5.0, "unit": "cloves", "urgency": None},
                    {"name": "ginger", "quantity": 1.0, "unit": "piece", "urgency": None},
                    {"name": "rice", "quantity": 3.0, "unit": "cups", "urgency": None},
                    {"name": "spinach", "quantity": 2.0, "unit": "cups", "urgency": 3},
                    {"name": "eggs", "quantity": 4.0, "unit": "pieces", "urgency": None},
                    {"name": "gochujang", "quantity": 3.0, "unit": "tbsp", "urgency": None},
                    {"name": "mushrooms", "quantity": 200.0, "unit": "g", "urgency": 2},
                ],
            },
        },
    ]


async def main():
    parser = argparse.ArgumentParser(description="Generate test scenarios")
    parser.add_argument("--n", type=int, default=5, help="Number of LLM-generated scenarios")
    parser.add_argument("--static", action="store_true", help="Use static scenarios instead of LLM")
    parser.add_argument("--ollama-url", default=_DEFAULT_OLLAMA_URL)
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    args = parser.parse_args()

    if args.static:
        scenarios = get_static_scenarios()
    else:
        scenarios = await generate_scenarios_llm(args.n, args.ollama_url, args.model)

    print(json.dumps(scenarios, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
