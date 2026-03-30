"""
SQLAlchemy ORM models for the Smart Recipe Planner database schema.

Table summary:
    users               — User accounts (email + hashed password).
    user_preferences    — Dietary restrictions, cuisine affinities, equipment.
    recipe_cache        — Fetched and scraped recipe data, reused across sessions.
    session_pool        — Pipeline output for a single recommendation session.
    cook_history        — Recipes the user has marked as cooked.
    saved_recipes       — Recipes the user has bookmarked.
    behavior_events     — Analytics events for personalization and telemetry.
    session_log         — Session-level metadata and aggregate counters.

All primary keys are UUID strings generated at insert time by ``_generate_uuid``.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _generate_uuid() -> str:
    """Return a new random UUID string suitable for use as a primary key."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class User(Base):
    """Registered user account.

    The ``email`` column has a unique index for fast login lookups. The
    ``hashed_password`` stores a bcrypt hash — raw passwords are never
    persisted.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    preferences = relationship("UserPreferences", back_populates="user", uselist=False)


class UserPreferences(Base):
    """Dietary and cooking preferences for a user.

    All JSON list columns default to an empty list. Boolean columns default
    to sensible values so callers can always safely iterate without ``None``
    checks. The ``updated_at`` timestamp is refreshed on every PUT request.
    """

    __tablename__ = "user_preferences"

    id = Column(String, primary_key=True, default=_generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    cuisine_preferences = Column(JSON, default=list)
    dietary_restrictions = Column(JSON, default=list)
    health_goal = Column(String, default="maintenance")
    time_preference = Column(String, default="moderate")
    meal_prep = Column(Boolean, default=False)
    cooking_equipment = Column(JSON, default=list)
    intolerances = Column(JSON, default=list)
    diet = Column(String, default=None, nullable=True)
    perishable_optimization = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="preferences")


class RecipeCache(Base):
    """Cached recipe data fetched and scraped from the web.

    Recipes are keyed by a UUID generated at insert time. The same cache row
    is reused across sessions for the same recipe — the pipeline uses
    ``db.merge()`` (upsert) rather than ``db.add()`` to avoid duplicates.

    ``ingredients`` is a JSON list of dicts (name, quantity, unit).
    ``instructions`` is a JSON list of dicts (step, text).
    """

    __tablename__ = "recipe_cache"

    id = Column(String, primary_key=True, default=_generate_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    image = Column(String, default="")
    prep_time = Column(Integer, default=0)
    cook_time = Column(Integer, default=0)
    total_time = Column(Integer, default=0)
    difficulty = Column(String, default="medium")
    servings = Column(Integer, default=4)
    cuisine = Column(String, default="")
    meal_type = Column(JSON, default=list)
    occasions = Column(JSON, default=list)
    rating = Column(Float, default=0.0)
    source = Column(String, default="web")
    source_url = Column(String, default="")
    cooking_equipment = Column(JSON, default=list)
    ingredients = Column(JSON, default=list)
    instructions = Column(JSON, default=list)
    cached_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SessionPool(Base):
    """Output of a single recipe recommendation pipeline run.

    ``recipes`` is a JSON list of slot dicts:
        {recipeId, score, status, shownAt, rankPosition}
    Status values: ``unshown`` | ``shown`` | ``saved``

    ``session_context`` stores the serialized ``SessionContextRequest`` used
    to start this session, enabling unlimited re-ideation rounds later.

    ``refetch_count`` tracks how many re-ideation rounds have been triggered
    for this pool (capped at ``MAX_REFETCH_ROUNDS`` in pipeline_service).
    """

    __tablename__ = "session_pool"

    id = Column(String, primary_key=True, default=_generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_id = Column(String, nullable=False, index=True)
    recipes = Column(JSON, default=list)
    session_context = Column(JSON, nullable=True)
    total_fetched = Column(Integer, default=0)
    shown_count = Column(Integer, default=0)
    saved_count = Column(Integer, default=0)
    refetch_count = Column(Integer, default=0)
    last_preference_inference = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CookHistory(Base):
    """Record of a recipe the user has cooked.

    The last 10 ``recipe_id`` values are passed to the LLM ideation stage as
    a "do not repeat" signal in future sessions. ``meal_type`` and
    ``serving_count`` are copied from the session context at cook time.
    """

    __tablename__ = "cook_history"

    id = Column(String, primary_key=True, default=_generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(String, nullable=False)
    cooked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    meal_type = Column(String, default="")
    serving_count = Column(Integer, default=2)
    session_id = Column(String, nullable=True)


class SavedRecipe(Base):
    """A recipe bookmarked by the user.

    Enforces a unique constraint at the application level (routes return 409
    on duplicates). The ``saved_at`` timestamp is used for sort order in the
    Saved screen (most recent first).
    """

    __tablename__ = "saved_recipes"

    id = Column(String, primary_key=True, default=_generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(String, nullable=False)
    saved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BehaviorEvent(Base):
    """A single analytics event emitted by the frontend.

    Events are fire-and-forget — the frontend does not retry or block on
    this endpoint. The ``metadata_`` column maps to the ``metadata`` SQL
    column (renamed to avoid shadowing Python's built-in).

    Common event types: session_started, recipe_shown, recipe_saved,
    recipe_unsaved, recipe_cooked, next_page, rerank_triggered.
    """

    __tablename__ = "behavior_events"

    id = Column(String, primary_key=True, default=_generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String, nullable=True)
    recipe_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SessionLog(Base):
    """Session-level aggregate counters for analytics.

    Tracks total swipes, refetches, and reranks per session, plus the final
    committed recipe (if any). Populated at session end.
    """

    __tablename__ = "session_log"

    id = Column(String, primary_key=True, default=_generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    meal_type = Column(String, default="")
    serving_count = Column(Integer, default=2)
    available_time_minutes = Column(Integer, default=45)
    available_prep_time_minutes = Column(Integer, nullable=True)
    available_cook_time_minutes = Column(Integer, nullable=True)
    occasion = Column(String, default="")
    vlm_ingredients = Column(JSON, default=list)
    total_swipes = Column(Integer, default=0)
    total_refetches = Column(Integer, default=0)
    total_reranks = Column(Integer, default=0)
    committed_recipe_id = Column(String, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
