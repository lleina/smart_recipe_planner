"""
Cooking history CRUD routes.

History entries are stored in the ``cook_history`` table and enriched with
display metadata (title, image, cook time) from the ``recipe_cache`` table
in a single batched query. The last 10 history entries are also passed to the
LLM ideation stage as a "do not repeat" signal.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models import CookHistory, RecipeCache
from app.schemas import CookHistoryCreate, CookHistoryOut

router = APIRouter(prefix="/api/history", tags=["history"])


def _enrich_history_entry(
    history_entry: CookHistory,
    cached_recipe: RecipeCache | None,
) -> CookHistoryOut:
    """Merge a ``CookHistory`` row with optional ``RecipeCache`` display data.

    Args:
        history_entry: The cook history database row.
        cached_recipe: Matching recipe cache entry, or ``None`` if not found.

    Returns:
        ``CookHistoryOut`` with display fields populated when available.
    """
    return CookHistoryOut(
        id=history_entry.id,
        recipe_id=history_entry.recipe_id,
        cooked_at=history_entry.cooked_at,
        meal_type=history_entry.meal_type,
        serving_count=history_entry.serving_count,
        session_id=history_entry.session_id,
        recipe_title=cached_recipe.title if cached_recipe else None,
        recipe_image=cached_recipe.image if cached_recipe else None,
        recipe_cook_time=cached_recipe.cook_time if cached_recipe else None,
    )


@router.get("", response_model=list[CookHistoryOut])
async def list_cooking_history(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's cooking history, most recent first.

    Enriches each entry with recipe display data (title, image, cook time)
    using a single batched query — no N+1 database calls.

    Args:
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        List of ``CookHistoryOut`` ordered by ``cooked_at`` descending.
    """
    history_result = await db.execute(
        select(CookHistory)
        .where(CookHistory.user_id == user_id)
        .order_by(CookHistory.cooked_at.desc())
    )
    history_rows = history_result.scalars().all()

    recipe_ids = list({row.recipe_id for row in history_rows})
    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id.in_(recipe_ids))
    )
    recipe_cache_by_id = {recipe.id: recipe for recipe in cache_result.scalars().all()}

    return [
        _enrich_history_entry(row, recipe_cache_by_id.get(row.recipe_id))
        for row in history_rows
    ]


@router.post("", response_model=CookHistoryOut, status_code=201)
async def log_cooked_recipe(
    body: CookHistoryCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Log that the authenticated user cooked a recipe.

    The recorded meal type and serving count are taken from the session context
    in which the recipe was discovered. This entry will be included in the
    "do not repeat" signal passed to future LLM ideation rounds.

    Args:
        body: Payload with ``recipe_id``, ``meal_type``, ``serving_count``,
            and optional ``session_id``.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        ``CookHistoryOut`` for the newly created history entry.
    """
    new_entry = CookHistory(
        user_id=user_id,
        recipe_id=body.recipe_id,
        meal_type=body.meal_type,
        serving_count=body.serving_count,
        session_id=body.session_id,
    )
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)

    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id == body.recipe_id)
    )
    cached_recipe = cache_result.scalar_one_or_none()

    return _enrich_history_entry(new_entry, cached_recipe)


@router.delete("/{entry_id}", status_code=204)
async def delete_history_entry(
    entry_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single cooking history entry.

    Verifies that the entry belongs to the authenticated user before deletion
    to prevent cross-user data deletion.

    Args:
        entry_id: Primary key of the ``CookHistory`` row to delete.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Raises:
        HTTPException(404): If no matching history entry is found for this user.
    """
    history_result = await db.execute(
        select(CookHistory).where(
            CookHistory.id == entry_id,
            CookHistory.user_id == user_id,
        )
    )
    history_entry = history_result.scalar_one_or_none()
    if not history_entry:
        raise HTTPException(status_code=404, detail="History entry not found")

    await db.delete(history_entry)
    await db.commit()
