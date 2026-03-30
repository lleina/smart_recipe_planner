"""
Recipe lookup routes.

Provides two capabilities:
  1. Fetch a single recipe by ID from the local ``recipe_cache`` table.
  2. Generate LLM-powered ingredient substitution suggestions for recipes
     where the user is missing one or more ingredients.

All recipe data is sourced from the local cache (populated by the pipeline
service) rather than re-fetching from the web, so responses are instant.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models import RecipeCache
from app.schemas import RecipeOut
from app.services import llm_service

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


class SubstitutionRequest(BaseModel):
    """Request body for the ingredient substitution endpoint.

    Attributes:
        recipe_ingredients: Full ingredient list from the recipe.
        user_ingredients: Ingredients the user has available (may be empty).
    """

    recipe_ingredients: list[str]
    user_ingredients: list[str] = []


def _serialize_cached_recipe(cached_recipe: RecipeCache) -> RecipeOut:
    """Convert a ``RecipeCache`` ORM row into a ``RecipeOut`` response object.

    Applies safe defaults for all nullable database columns so the API
    response always conforms to the schema without ``None`` values on
    optional string/list fields.

    Args:
        cached_recipe: The ``RecipeCache`` ORM instance to serialize.

    Returns:
        Fully populated ``RecipeOut`` ready for the API response.
    """
    return RecipeOut(
        id=cached_recipe.id,
        title=cached_recipe.title,
        description=cached_recipe.description or "",
        image=cached_recipe.image or "",
        prep_time=cached_recipe.prep_time or 0,
        cook_time=cached_recipe.cook_time or 0,
        total_time=cached_recipe.total_time or 0,
        difficulty=cached_recipe.difficulty or "medium",
        servings=cached_recipe.servings or 4,
        cuisine=cached_recipe.cuisine or "",
        meal_type=cached_recipe.meal_type or [],
        occasions=cached_recipe.occasions or [],
        rating=cached_recipe.rating or 0.0,
        source_url=cached_recipe.source_url or "",
        cooking_equipment=cached_recipe.cooking_equipment or [],
        ingredients=cached_recipe.ingredients or [],
        instructions=cached_recipe.instructions or [],
        score=0.0,
    )


@router.get("/{recipe_id}", response_model=RecipeOut)
async def get_recipe_by_id(
    recipe_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single cached recipe by its ID.

    Recipes are served from the local ``recipe_cache`` table, which is
    populated by the pipeline service. The response is immediate — no
    web requests are made.

    Args:
        recipe_id: The recipe's unique cache ID (UUID).
        user_id: Authenticated user's ID (required for auth; not used here).
        db: Async database session (injected by FastAPI).

    Returns:
        ``RecipeOut`` with all recipe fields.

    Raises:
        HTTPException(404): If the recipe is not found in the local cache.
    """
    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id == recipe_id)
    )
    cached_recipe = cache_result.scalar_one_or_none()
    if not cached_recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return _serialize_cached_recipe(cached_recipe)


@router.post("/{recipe_id}/substitutions")
async def get_ingredient_substitutions(
    recipe_id: str,
    body: SubstitutionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Generate ingredient substitution suggestions for a recipe.

    Compares the recipe's ingredient list against the user's available
    ingredients and asks the LLM to suggest substitutes for any gaps.
    Substitutions prefer the user's actual pantry over generic alternatives
    when possible.

    This endpoint is called proactively (pre-fetched) by the Discover screen
    so that substitution data is ready instantly when the user opens recipe
    detail.

    Args:
        recipe_id: The recipe's cache ID (used for logging context only).
        body: Contains ``recipe_ingredients`` and ``user_ingredients`` lists.
        user_id: Authenticated user's ID (required for auth; not used here).

    Returns:
        ``{"substitutions": [...]}`` where each entry describes one missing
        ingredient and its viable substitutes.
    """
    substitution_results = await llm_service.suggest_substitutions(
        recipe_ingredients=body.recipe_ingredients,
        user_ingredients=body.user_ingredients,
    )
    return {"substitutions": substitution_results}
