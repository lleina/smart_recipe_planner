"""
User profile and preferences routes.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User, UserPreferences
from app.schemas import PreferencesUpdate, PreferencesResponse
from app.auth import get_current_user_id

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile")
async def get_profile(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        raise HTTPException(status_code=404, detail="Preferences not found")
    return PreferencesResponse(
        cuisine_preferences=prefs.cuisine_preferences or [],
        dietary_restrictions=prefs.dietary_restrictions or [],
        health_goal=prefs.health_goal or "maintenance",
        time_preference=prefs.time_preference or "moderate",
        meal_prep=prefs.meal_prep or False,
        cooking_equipment=prefs.cooking_equipment or [],
        perishable_optimization=prefs.perishable_optimization
        if prefs.perishable_optimization is not None else True,
        updated_at=prefs.updated_at,
    )


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    body: PreferencesUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)

    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(prefs, key, value)
    prefs.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(prefs)

    return PreferencesResponse(
        cuisine_preferences=prefs.cuisine_preferences or [],
        dietary_restrictions=prefs.dietary_restrictions or [],
        health_goal=prefs.health_goal or "maintenance",
        time_preference=prefs.time_preference or "moderate",
        meal_prep=prefs.meal_prep or False,
        cooking_equipment=prefs.cooking_equipment or [],
        perishable_optimization=prefs.perishable_optimization
        if prefs.perishable_optimization is not None else True,
        updated_at=prefs.updated_at,
    )
