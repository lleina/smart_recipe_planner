"""
Recipe lookup routes.
Provides individual recipe fetch by ID from the local cache,
plus LLM-powered ingredient substitution suggestions.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import RecipeCache
from app.schemas import RecipeOut
from app.auth import get_current_user_id
from app.services import llm_service

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.get("/{recipe_id}", response_model=RecipeOut)
async def get_recipe(
    recipe_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RecipeCache).where(RecipeCache.id == recipe_id)
    )
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return RecipeOut(
        id=recipe.id,
        title=recipe.title,
        description=recipe.description or "",
        image=recipe.image or "",
        prep_time=recipe.prep_time or 0,
        cook_time=recipe.cook_time or 0,
        total_time=recipe.total_time or 0,
        difficulty=recipe.difficulty or "medium",
        servings=recipe.servings or 4,
        cuisine=recipe.cuisine or "",
        meal_type=recipe.meal_type or [],
        occasions=recipe.occasions or [],
        rating=recipe.rating or 0.0,
        source_url=recipe.source_url or "",
        cooking_equipment=recipe.cooking_equipment or [],
        ingredients=recipe.ingredients or [],
        instructions=recipe.instructions or [],
        score=0.0,
    )


# ---------------------------------------------------------------------------
# LLM ingredient substitution
# ---------------------------------------------------------------------------

class SubstitutionRequest(BaseModel):
    recipe_ingredients: list[str]
    user_ingredients: list[str] = []


@router.post("/{recipe_id}/substitutions")
async def get_substitutions(
    recipe_id: str,
    body: SubstitutionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Ask the LLM to match recipe ingredients against the user's pantry and
    suggest substitutions for missing items.
    """
    results = await llm_service.suggest_substitutions(
        recipe_ingredients=body.recipe_ingredients,
        user_ingredients=body.user_ingredients,
    )
    return {"substitutions": results}
