"""
Behavioral event ingestion routes.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import BehaviorEvent
from app.schemas import EventCreate
from app.auth import get_current_user_id

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("", status_code=201)
async def create_event(
    body: EventCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    event = BehaviorEvent(
        user_id=user_id,
        session_id=body.session_id,
        recipe_id=body.recipe_id,
        event_type=body.event_type,
        metadata_=body.metadata,
    )
    db.add(event)
    await db.commit()
    return {"status": "ok"}
