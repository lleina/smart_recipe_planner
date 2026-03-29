"""
Pydantic schemas for request/response validation.
"""

from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel
from typing import Optional
from datetime import datetime


def _camel_case_alias(field_name: str) -> str:
    """Convert snake_case to camelCase (e.g. meal_type -> mealType)."""
    return to_camel(field_name)


# --- Auth ---

class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    access_token: str
    refresh_token: str
    user_id: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    refresh_token: str


# --- User Preferences ---

class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    cuisine_preferences: Optional[list[str]] = None
    dietary_restrictions: Optional[list[str]] = None
    health_goal: Optional[str] = None
    time_preference: Optional[str] = None
    meal_prep: Optional[bool] = None
    cooking_equipment: Optional[list[str]] = None
    perishable_optimization: Optional[bool] = None


class PreferencesResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    cuisine_preferences: list[str]
    dietary_restrictions: list[str]
    health_goal: str
    time_preference: str
    meal_prep: bool
    cooking_equipment: list[str]
    perishable_optimization: bool
    updated_at: datetime


# --- VLM ---

class IngredientItem(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    name: str
    confidence: float = 0.0
    category: str = "shelf-stable"
    urgency: Optional[int] = None
    estimated_quantity: float = 1.0
    unit: str = "pieces"


class VlmResponse(BaseModel):
    ingredients: list[IngredientItem]


# --- Recipe Pipeline ---

class SessionContextRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    meal_type: str = "dinner"
    serving_count: int = 2
    available_time_minutes: int = 45
    available_prep_time_minutes: Optional[int] = None
    available_cook_time_minutes: Optional[int] = None
    occasion: Optional[str] = None
    available_ingredients: list[IngredientItem] = []


class RecommendRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    user_id: str
    session_context: SessionContextRequest
    # Per-request ranking mode override. Falls back to RANKING_MODE config when None.
    # Values: "hybrid" | "rules_only" | "llm_only"
    ranking_mode: Optional[str] = None


class RecipeOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    id: str
    spoonacular_id: Optional[str] = None
    title: str
    description: str = ""
    image: str = ""
    prep_time: int = 0
    cook_time: int = 0
    total_time: int = 0
    difficulty: str = "medium"
    servings: int = 4
    cuisine: str = ""
    meal_type: list[str] = []
    occasions: list[str] = []
    rating: float = 0.0
    source_url: str = ""
    cooking_equipment: list[str] = []
    ingredients: list[dict] = []
    instructions: list[dict] = []
    score: float = 0.0


class RecommendResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    session_pool_id: str
    recipes: list[RecipeOut]
    pool_size: int
    shown_count: int
    # Recorded for observability / A-B comparison
    ranking_mode_used: Optional[str] = None


class NextBatchResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    recipes: list[RecipeOut]
    shown_count: int
    pool_size: int
    refetch_triggered: bool = False


class RerankRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    user_id: str
    session_pool_id: str
    liked_recipe_id: str
    action: str = "saved"


class RerankResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    message: str
    preference_inference: str


# --- History ---

class CookHistoryCreate(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    recipe_id: str
    meal_type: str = ""
    serving_count: int = 2
    session_id: Optional[str] = None


class CookHistoryOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    id: str
    recipe_id: str
    cooked_at: datetime
    meal_type: str
    serving_count: int
    session_id: Optional[str]
    # Enriched from recipe_cache for display
    recipe_title: Optional[str] = None
    recipe_image: Optional[str] = None
    recipe_cook_time: Optional[int] = None


# --- Saved ---

class SaveRecipeRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    recipe_id: str


class SavedRecipeOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True, serialize_by_alias=True)
    id: str
    recipe_id: str
    saved_at: datetime
    # Enriched from recipe_cache for display
    recipe_title: Optional[str] = None
    recipe_image: Optional[str] = None
    recipe_cook_time: Optional[int] = None


# --- Events ---

class EventCreate(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case_alias, populate_by_name=True)
    session_id: Optional[str] = None
    recipe_id: Optional[str] = None
    event_type: str
    metadata: dict = {}


# --- Generic ---

class ErrorResponse(BaseModel):
    error: str
    fallback: bool = False
