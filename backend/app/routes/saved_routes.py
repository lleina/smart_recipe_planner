"""
Saved recipes CRUD routes.

Saved recipes are stored in the ``saved_recipes`` table and enriched with
display metadata (title, image, cook time) from the ``recipe_cache`` table in
a single batched query to avoid N+1 database calls.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models import RecipeCache, SavedRecipe
from app.schemas import SaveRecipeRequest, SavedRecipeOut

router = APIRouter(prefix="/api/saved", tags=["saved"])


def _enrich_saved_entry(
    saved_entry: SavedRecipe,
    cached_recipe: RecipeCache | None,
) -> SavedRecipeOut:
    """Merge a ``SavedRecipe`` row with optional ``RecipeCache`` display data.

    Args:
        saved_entry: The saved recipe database row.
        cached_recipe: Matching recipe cache entry, or ``None`` if not found.

    Returns:
        ``SavedRecipeOut`` with display fields populated when available.
    """
    return SavedRecipeOut(
        id=saved_entry.id,
        recipe_id=saved_entry.recipe_id,
        saved_at=saved_entry.saved_at,
        recipe_title=cached_recipe.title if cached_recipe else None,
        recipe_image=cached_recipe.image if cached_recipe else None,
        recipe_cook_time=cached_recipe.cook_time if cached_recipe else None,
    )


@router.get("", response_model=list[SavedRecipeOut])
async def list_saved_recipes(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return all saved recipes for the authenticated user, newest first.

    Enriches each entry with title, image, and cook time from the recipe cache
    using a single batched query (no N+1 calls).

    Args:
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        List of ``SavedRecipeOut`` objects ordered by ``saved_at`` descending.
    """
    saved_rows_result = await db.execute(
        select(SavedRecipe)
        .where(SavedRecipe.user_id == user_id)
        .order_by(SavedRecipe.saved_at.desc())
    )
    saved_rows = saved_rows_result.scalars().all()

    recipe_ids = list({row.recipe_id for row in saved_rows})
    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id.in_(recipe_ids))
    )
    recipe_cache_by_id = {recipe.id: recipe for recipe in cache_result.scalars().all()}

    return [
        _enrich_saved_entry(row, recipe_cache_by_id.get(row.recipe_id))
        for row in saved_rows
    ]


@router.post("", response_model=SavedRecipeOut, status_code=201)
async def save_recipe(
    body: SaveRecipeRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Save a recipe to the authenticated user's collection.

    Idempotent on the recipe level — saving the same recipe twice returns 409
    rather than creating a duplicate entry.

    Args:
        body: Request payload containing the ``recipe_id`` to save.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        ``SavedRecipeOut`` for the newly created saved-recipe entry.

    Raises:
        HTTPException(409): If the recipe is already in the user's collection.
    """
    duplicate_check = await db.execute(
        select(SavedRecipe).where(
            SavedRecipe.user_id == user_id,
            SavedRecipe.recipe_id == body.recipe_id,
        )
    )
    if duplicate_check.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Recipe already saved")

    new_entry = SavedRecipe(user_id=user_id, recipe_id=body.recipe_id)
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)

    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id == body.recipe_id)
    )
    cached_recipe = cache_result.scalar_one_or_none()

    return _enrich_saved_entry(new_entry, cached_recipe)


@router.delete("/{entry_id}", status_code=204)
async def unsave_recipe(
    entry_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove a saved recipe from the authenticated user's collection.

    Accepts either the ``SavedRecipe.id`` (primary key) or the ``recipe_id``
    (the recipe's cache ID) to support both frontend variants. The primary key
    lookup is tried first for correctness and efficiency.

    Args:
        entry_id: Either the ``SavedRecipe.id`` or the recipe's ``recipe_id``.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Raises:
        HTTPException(404): If no matching saved entry is found for this user.
    """
    # Prefer lookup by primary key; fall back to recipe_id for older clients.
    by_primary_key = await db.execute(
        select(SavedRecipe).where(
            SavedRecipe.id == entry_id,
            SavedRecipe.user_id == user_id,
        )
    )
    saved_entry = by_primary_key.scalar_one_or_none()

    if not saved_entry:
        by_recipe_id = await db.execute(
            select(SavedRecipe).where(
                SavedRecipe.recipe_id == entry_id,
                SavedRecipe.user_id == user_id,
            )
        )
        saved_entry = by_recipe_id.scalar_one_or_none()

    if not saved_entry:
        raise HTTPException(status_code=404, detail="Saved recipe not found")

    await db.delete(saved_entry)
    await db.commit()
