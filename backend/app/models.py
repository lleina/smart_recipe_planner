"""
SQLAlchemy ORM models matching the Agent_spec data models.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, relationship
import uuid


def gen_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    preferences = relationship("UserPreferences", back_populates="user", uselist=False)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    cuisine_preferences = Column(JSON, default=list)
    dietary_restrictions = Column(JSON, default=list)
    health_goal = Column(String, default="maintenance")
    time_preference = Column(String, default="moderate")
    meal_prep = Column(Boolean, default=False)
    cooking_equipment = Column(JSON, default=list)
    perishable_optimization = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="preferences")


class RecipeCache(Base):
    __tablename__ = "recipe_cache"

    id = Column(String, primary_key=True, default=gen_id)
    spoonacular_id = Column(String, unique=True, index=True)
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
    source = Column(String, default="spoonacular")
    source_url = Column(String, default="")
    cooking_equipment = Column(JSON, default=list)
    ingredients = Column(JSON, default=list)
    instructions = Column(JSON, default=list)
    cached_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SessionPool(Base):
    __tablename__ = "session_pool"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_id = Column(String, nullable=False, index=True)
    recipes = Column(JSON, default=list)
    total_fetched = Column(Integer, default=0)
    shown_count = Column(Integer, default=0)
    saved_count = Column(Integer, default=0)
    refetch_count = Column(Integer, default=0)
    last_preference_inference = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CookHistory(Base):
    __tablename__ = "cook_history"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(String, nullable=False)
    cooked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    meal_type = Column(String, default="")
    serving_count = Column(Integer, default=2)
    session_id = Column(String, nullable=True)


class SavedRecipe(Base):
    __tablename__ = "saved_recipes"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(String, nullable=False)
    saved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BehaviorEvent(Base):
    __tablename__ = "behavior_events"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String, nullable=True)
    recipe_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SessionLog(Base):
    __tablename__ = "session_log"

    id = Column(String, primary_key=True, default=gen_id)
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
