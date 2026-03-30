"""
User profile and preferences routes.

Preferences are stored in the ``user_preferences`` table and include dietary
restrictions, cuisine affinities, cooking equipment, and health goals. They
are applied globally to every recipe session for the authenticated user.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models import User, UserPreferences
from app.schemas import PreferencesResponse, PreferencesUpdate

router = APIRouter(prefix="/api/user", tags=["user"])


def _build_preferences_response(prefs: UserPreferences) -> PreferencesResponse:
    """Serialize a ``UserPreferences`` ORM object into a ``PreferencesResponse``.

    Applies safe defaults for nullable fields so the response schema is always
    fully populated — callers never need to handle ``None`` on required fields.

    Args:
        prefs: ``UserPreferences`` ORM instance to serialize.

    Returns:
        Fully populated ``PreferencesResponse`` ready for the API response.
    """
    return PreferencesResponse(
        cuisine_preferences=prefs.cuisine_preferences or [],
        dietary_restrictions=prefs.dietary_restrictions or [],
        health_goal=prefs.health_goal or "maintenance",
        time_preference=prefs.time_preference or "moderate",
        meal_prep=prefs.meal_prep or False,
        cooking_equipment=prefs.cooking_equipment or [],
        intolerances=prefs.intolerances or [],
        diet=prefs.diet,
        perishable_optimization=(
            prefs.perishable_optimization
            if prefs.perishable_optimization is not None
            else True
        ),
        updated_at=prefs.updated_at,
    )


@router.get("/profile")
async def get_profile(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return basic profile information for the authenticated user.

    Args:
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        Dict with ``id``, ``email``, and ``created_at``.

    Raises:
        HTTPException(404): If the user record no longer exists.
    """
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's dietary and cooking preferences.

    Args:
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        ``PreferencesResponse`` with all preference fields.

    Raises:
        HTTPException(404): If no preferences record exists for this user.
    """
    prefs_result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = prefs_result.scalar_one_or_none()
    if not prefs:
        raise HTTPException(status_code=404, detail="Preferences not found")

    return _build_preferences_response(prefs)


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    body: PreferencesUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's dietary and cooking preferences.

    Only fields present in the request body are updated (partial update).
    If no preferences record exists yet, one is created automatically —
    this supports the offline-first onboarding flow where preferences are
    synced to the backend on the first server interaction.

    Args:
        body: Partial preferences payload; ``None`` fields are ignored.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        Updated ``PreferencesResponse`` with all fields.
    """
    prefs_result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = prefs_result.scalar_one_or_none()

    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)

    for field_name, field_value in body.model_dump(exclude_none=True).items():
        setattr(prefs, field_name, field_value)
    prefs.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(prefs)

    return _build_preferences_response(prefs)
