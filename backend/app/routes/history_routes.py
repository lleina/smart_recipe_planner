"""
Cook history CRUD routes.
Enriches list responses with recipe title/image from recipe_cache.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import CookHistory, RecipeCache
from app.schemas import CookHistoryCreate, CookHistoryOut
from app.auth import get_current_user_id

router = APIRouter(prefix="/api/history", tags=["history"])


def _enrich(entry: CookHistory, recipe: RecipeCache | None) -> CookHistoryOut:
    return CookHistoryOut(
        id=entry.id,
        recipe_id=entry.recipe_id,
        cooked_at=entry.cooked_at,
        meal_type=entry.meal_type,
        serving_count=entry.serving_count,
        session_id=entry.session_id,
        recipe_title=recipe.title if recipe else None,
        recipe_image=recipe.image if recipe else None,
        recipe_cook_time=recipe.cook_time if recipe else None,
    )


@router.get("", response_model=list[CookHistoryOut])
async def list_history(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows_result = await db.execute(
        select(CookHistory)
        .where(CookHistory.user_id == user_id)
        .order_by(CookHistory.cooked_at.desc())
    )
    rows = rows_result.scalars().all()

    recipe_ids = list({r.recipe_id for r in rows})
    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id.in_(recipe_ids))
    )
    cache = {r.id: r for r in cache_result.scalars().all()}

    return [_enrich(r, cache.get(r.recipe_id)) for r in rows]


@router.post("", response_model=CookHistoryOut, status_code=201)
async def create_history(
    body: CookHistoryCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entry = CookHistory(
        user_id=user_id,
        recipe_id=body.recipe_id,
        meal_type=body.meal_type,
        serving_count=body.serving_count,
        session_id=body.session_id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    cache_result = await db.execute(
        select(RecipeCache).where(RecipeCache.id == body.recipe_id)
    )
    recipe = cache_result.scalar_one_or_none()

    return _enrich(entry, recipe)


@router.delete("/{entry_id}", status_code=204)
async def delete_history(
    entry_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CookHistory).where(
            CookHistory.id == entry_id, CookHistory.user_id == user_id
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found")
    await db.delete(entry)
    await db.commit()
