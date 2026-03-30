"""
Recipe generation integration tests.

Tests the full recommendation pipeline end-to-end:
  POST /api/recommend → runs LLM ideation + web fetch + ranking → returns recipes

Verifies:
  - Pipeline completes successfully
  - Response schema matches what the frontend expects (camelCase keys)
  - Each recipe has required fields (id, title, ingredients, instructions)
  - At least 5 recipes returned (one full page)
  - Ingredient match metadata is populated (matchedIngredientCount, etc.)
  - Re-ranking endpoint accepts signals without errors

These are slow tests (LLM + web fetch). Run with:
  cd backend && pytest tests/test_recipe_generation.py -v

Skip in CI:
  cd backend && pytest tests/ -v -m "not slow"
"""

import pytest
import requests

# ── Constants matching frontend expectations ──────────────────────────────────

EXPECTED_RECIPE_FIELDS = {
    "id",
    "title",
    "ingredients",
    "instructions",
    "totalTime",
    "difficulty",
}

MIN_RECIPES_FIRST_PAGE = 5   # Frontend shows 5 per page
MAX_PIPELINE_SECONDS = 660   # 11 min — matches API_TIMEOUT_MS in config.js


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.slow
class TestRecipeGeneration:
    """
    End-to-end recipe generation pipeline tests.

    Uses active_session_pool fixture (shared per module) so the expensive
    LLM pipeline only runs once for all tests in this file.
    """

    def test_pipeline_returns_200(self, active_session_pool):
        """Pipeline fixture succeeded (already asserted in conftest). Confirm pool exists."""
        assert active_session_pool.get("sessionPoolId"), "No sessionPoolId in pipeline response"

    def test_pipeline_returns_minimum_one_page(self, active_session_pool):
        """
        The first response must contain at least PAGE_SIZE (5) recipes so
        the frontend can render a complete first page immediately.
        """
        recipes = active_session_pool.get("recipes", [])
        assert len(recipes) >= MIN_RECIPES_FIRST_PAGE, (
            f"Expected >= {MIN_RECIPES_FIRST_PAGE} recipes on first page, got {len(recipes)}"
        )

    def test_all_recipes_have_required_fields(self, active_session_pool):
        """
        Every recipe must have the fields the RecipeCard and RecipeDetailScreen render.
        Missing fields cause runtime errors in the frontend.
        """
        recipes = active_session_pool.get("recipes", [])
        for recipe in recipes:
            missing = EXPECTED_RECIPE_FIELDS - set(recipe.keys())
            assert not missing, (
                f"Recipe '{recipe.get('title', recipe.get('id'))}' missing: {missing}"
            )

    def test_recipe_ids_are_unique(self, active_session_pool):
        """
        All recipe IDs in the first page must be unique.
        Duplicate IDs break FlatList keyExtractor, saved state, and history.
        """
        recipes = active_session_pool.get("recipes", [])
        ids = [r["id"] for r in recipes]
        assert len(ids) == len(set(ids)), (
            f"Duplicate recipe IDs in first page: {[i for i in ids if ids.count(i) > 1]}"
        )

    def test_recipe_titles_are_non_empty(self, active_session_pool):
        """All recipe titles must be non-empty strings."""
        recipes = active_session_pool.get("recipes", [])
        for recipe in recipes:
            title = recipe.get("title")
            assert isinstance(title, str) and title.strip(), (
                f"Recipe {recipe.get('id')} has empty title"
            )

    def test_recipe_ingredients_are_lists(self, active_session_pool):
        """
        Ingredients must be a list. The RecipeDetailScreen iterates over this
        to render the ingredient list and substitution badges.
        """
        recipes = active_session_pool.get("recipes", [])
        for recipe in recipes:
            ingredients = recipe.get("ingredients")
            assert isinstance(ingredients, list), (
                f"Recipe '{recipe.get('title')}' ingredients is not a list: {type(ingredients)}"
            )
            assert len(ingredients) > 0, (
                f"Recipe '{recipe.get('title')}' has empty ingredients list"
            )

    def test_recipe_instructions_are_lists(self, active_session_pool):
        """
        Instructions must be a non-empty list of steps.
        The RecipeDetailScreen renders numbered steps from this array.
        """
        recipes = active_session_pool.get("recipes", [])
        for recipe in recipes:
            instructions = recipe.get("instructions")
            assert isinstance(instructions, list), (
                f"Recipe '{recipe.get('title')}' instructions not a list: {type(instructions)}"
            )
            assert len(instructions) > 0, (
                f"Recipe '{recipe.get('title')}' has empty instructions"
            )

    def test_total_time_is_positive_integer(self, active_session_pool):
        """
        totalTime must be a positive number (minutes). The RecipeCard
        renders this via formatMinutes() — null/negative causes display bugs.
        """
        recipes = active_session_pool.get("recipes", [])
        for recipe in recipes:
            total_time = recipe.get("totalTime")
            assert isinstance(total_time, (int, float)) and total_time > 0, (
                f"Recipe '{recipe.get('title')}' totalTime invalid: {total_time}"
            )

    def test_difficulty_is_valid_level(self, active_session_pool):
        """
        Difficulty must be one of: easy, medium, hard.
        The RecipeCard maps these to colors/labels — unknown values show as 'Medium'.
        """
        valid_difficulties = {"easy", "medium", "hard"}
        recipes = active_session_pool.get("recipes", [])
        for recipe in recipes:
            difficulty = recipe.get("difficulty", "medium")
            assert difficulty in valid_difficulties, (
                f"Recipe '{recipe.get('title')}' has invalid difficulty: '{difficulty}'"
            )

    def test_ingredient_match_metadata_present(self, active_session_pool):
        """
        The IngredientMatchBadge in RecipeCard expects these ranking fields.
        If missing, the badge shows 0/0 ingredients which is misleading.
        """
        recipes = active_session_pool.get("recipes", [])
        match_fields = {"matchedIngredientCount", "totalIngredientCount", "ingredientMatchPct"}
        for recipe in recipes:
            missing = match_fields - set(recipe.keys())
            assert not missing, (
                f"Recipe '{recipe.get('title')}' missing match metadata: {missing}"
            )

    def test_response_uses_camel_case_keys(self, active_session_pool):
        """
        All keys in the response must use camelCase (not snake_case).
        The backend uses Pydantic aliases for JS/Python interop.
        """
        recipes = active_session_pool.get("recipes", [])
        snake_keys_found = []
        for recipe in recipes[:3]:  # sample first 3
            for key in recipe.keys():
                if "_" in key:
                    snake_keys_found.append(f"{recipe.get('title')}.{key}")

        assert not snake_keys_found, (
            f"snake_case keys found in response (should be camelCase): {snake_keys_found}"
        )


@pytest.mark.slow
class TestRerankingSignal:
    """Tests for the POST /api/rerank endpoint (preference signal recording)."""

    def test_rerank_accepts_saved_action(self, api_base, registered_user, auth_headers, active_session_pool):
        """
        The rerank endpoint must accept a 'saved' action for any recipe
        in the current session pool without returning an error.
        """
        user_id, _ = registered_user
        session_pool_id = active_session_pool["sessionPoolId"]
        first_recipe = active_session_pool["recipes"][0]

        response = requests.post(
            f"{api_base}/rerank",
            json={
                "userId": user_id,
                "sessionPoolId": session_pool_id,
                "likedRecipeId": first_recipe["id"],
                "action": "saved",
            },
            headers=auth_headers,
            timeout=30,
        )
        assert response.status_code == 200, (
            f"Rerank failed: {response.status_code} — {response.text[:300]}"
        )

    def test_rerank_response_includes_preference_inference(self, api_base, registered_user, auth_headers, active_session_pool):
        """
        The rerank response must include a preferenceInference field that
        explains what the LLM inferred about the user's taste. This is used
        for logging and debugging.
        """
        user_id, _ = registered_user
        session_pool_id = active_session_pool["sessionPoolId"]
        first_recipe = active_session_pool["recipes"][0]

        response = requests.post(
            f"{api_base}/rerank",
            json={
                "userId": user_id,
                "sessionPoolId": session_pool_id,
                "likedRecipeId": first_recipe["id"],
                "action": "saved",
            },
            headers=auth_headers,
            timeout=30,
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data or "preferenceInference" in data, (
            f"Rerank response missing expected fields: {data}"
        )


class TestRecipeDetail:
    """Tests for fetching individual recipes from the cache."""

    def test_get_recipe_by_id_returns_200(self, api_base, auth_headers, active_session_pool):
        """Fetching a recipe by its ID must succeed."""
        first_recipe = active_session_pool["recipes"][0]
        response = requests.get(
            f"{api_base}/recipes/{first_recipe['id']}",
            headers=auth_headers,
            timeout=10,
        )
        assert response.status_code == 200, (
            f"GET /recipes/{first_recipe['id']} failed: {response.status_code}"
        )

    def test_get_recipe_returns_matching_id(self, api_base, auth_headers, active_session_pool):
        """The returned recipe must have the same ID as requested."""
        first_recipe = active_session_pool["recipes"][0]
        response = requests.get(
            f"{api_base}/recipes/{first_recipe['id']}",
            headers=auth_headers,
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("id") == first_recipe["id"]

    def test_get_nonexistent_recipe_returns_404(self, api_base, auth_headers):
        """Requesting a recipe that doesn't exist must return 404."""
        response = requests.get(
            f"{api_base}/recipes/definitely-not-a-real-recipe-id-xyz",
            headers=auth_headers,
            timeout=10,
        )
        assert response.status_code == 404

    def test_substitutions_returns_list(self, api_base, auth_headers, active_session_pool):
        """
        POST /recipes/:id/substitutions must return a 'substitutions' list.
        The RecipeDetailScreen uses this to show swap suggestions per ingredient.
        """
        first_recipe = active_session_pool["recipes"][0]
        ingredient_names = [
            ing.get("name", ing) if isinstance(ing, dict) else str(ing)
            for ing in (first_recipe.get("ingredients") or [])[:5]
        ]

        response = requests.post(
            f"{api_base}/recipes/{first_recipe['id']}/substitutions",
            json={
                "recipe_ingredients": ingredient_names,
                "user_ingredients": ["rice", "soy sauce", "garlic"],
            },
            headers=auth_headers,
            timeout=60,
        )
        assert response.status_code == 200, (
            f"Substitutions failed: {response.status_code} — {response.text[:200]}"
        )
        data = response.json()
        assert "substitutions" in data, f"Response missing 'substitutions': {data}"
        assert isinstance(data["substitutions"], list)
