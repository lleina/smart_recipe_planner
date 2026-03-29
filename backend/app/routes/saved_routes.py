"""
Saved recipes CRUD routes.
Enriches list responses with recipe title/image from recipe_cache.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import SavedRecipe, RecipeCache
from app.schemas import SaveRecipeRequest, SavedRecipeOut
from app.auth import get_current_user_id

router = APIRouter(prefix="/api/saved", tags=["saved"])


def _enrich(entry: SavedRecipe, recipe: RecipeCache | None) -> SavedRecipeOut:
    return SavedRecipeOut(
        id=entry.id,
        recipe_id=entry.recipe_id,
        saved_at=entry.saved_at,
        recipe_title=recipe.title if recipe else None,
        recipe_image=recipe.image if recipe else None,
        recipe_cook_time=recipe.cook_time if recipe else None,
    )


@router.get("", response_model=list[SavedRecipeOut])
async def list_saved(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows_result = await db.execute(
        select(SavedRecipe)
        .where(SavedRecipe.user_id == user_id)
        .order_by(SavedRecipe.saved_at.desc())
    )
    rows = rows_result.scalars().all()

    recipe_ids = list({r.recipe_id for r in rows})
    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id.in_(recipe_ids))
    )
    cache = {r.id: r for r in cache_result.scalars().all()}

    return [_enrich(r, cache.get(r.recipe_id)) for r in rows]


@router.post("", response_model=SavedRecipeOut, status_code=201)
async def save_recipe(
    body: SaveRecipeRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(SavedRecipe).where(
            SavedRecipe.user_id == user_id,
            SavedRecipe.recipe_id == body.recipe_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Recipe already saved")

    entry = SavedRecipe(user_id=user_id, recipe_id=body.recipe_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id == body.recipe_id)
    )
    recipe = cache_result.scalar_one_or_none()

    return _enrich(entry, recipe)


@router.delete("/{entry_id}", status_code=204)
async def unsave_recipe(
    entry_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # Try by entry primary key first (frontend sends the SavedRecipe.id)
    result = await db.execute(
        select(SavedRecipe).where(
            SavedRecipe.id == entry_id, SavedRecipe.user_id == user_id
        )
    )
    entry = result.scalar_one_or_none()
    # Fallback: try by recipe_id for backwards compat
    if not entry:
        result = await db.execute(
            select(SavedRecipe).where(
                SavedRecipe.recipe_id == entry_id, SavedRecipe.user_id == user_id
            )
        )
        entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Saved recipe not found")
    await db.delete(entry)
    await db.commit()
