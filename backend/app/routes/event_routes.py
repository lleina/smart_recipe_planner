"""
Behavioral event ingestion routes.

Events are lightweight analytics records used for future personalization and
usage telemetry. They are fire-and-forget from the frontend — errors here
must never surface to the user. Stored in the ``behavior_events`` table.

Tracked event types (not exhaustive):
    session_started, recipe_shown, recipe_saved, recipe_unsaved,
    recipe_cooked, next_page, rerank_triggered
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models import BehaviorEvent
from app.schemas import EventCreate

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("", status_code=201)
async def record_behavior_event(
    body: EventCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Record a single user behavior event for analytics and personalization.

    This endpoint is intentionally lenient — it should never be the source of
    a user-visible error. The frontend calls it fire-and-forget. All fields
    except ``event_type`` are optional.

    Args:
        body: Event payload with ``event_type``, optional ``session_id``,
            optional ``recipe_id``, and a flexible ``metadata`` dict.
        user_id: Authenticated user's ID (extracted from JWT by dependency).
        db: Async database session (injected by FastAPI).

    Returns:
        ``{"status": "ok"}`` on success.
    """
    new_event = BehaviorEvent(
        user_id=user_id,
        session_id=body.session_id,
        recipe_id=body.recipe_id,
        event_type=body.event_type,
        metadata_=body.metadata,
    )
    db.add(new_event)
    await db.commit()
    return {"status": "ok"}
