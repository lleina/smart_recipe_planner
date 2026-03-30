"""
Pydantic request/response schemas for the Smart Recipe Planner API.

All schemas that travel between the Python backend and the JavaScript frontend
use camelCase aliases (via ``_to_camel_case``) so both sides can use their
idiomatic naming conventions without manual mapping.

Schema groups:
    Auth         — RegisterRequest, LoginRequest, TokenResponse, RefreshRequest
    Preferences  — PreferencesUpdate, PreferencesResponse
    VLM          — IngredientItem, VlmResponse
    Pipeline     — SessionContextRequest, RecommendRequest, RecipeOut,
                   RecommendResponse, NextBatchResponse, RerankRequest,
                   RerankResponse
    History      — CookHistoryCreate, CookHistoryOut
    Saved        — SaveRecipeRequest, SavedRecipeOut
    Events       — EventCreate
    Generic      — ErrorResponse
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _to_camel_case(field_name: str) -> str:
    """Convert a snake_case field name to camelCase for JSON serialization.

    Example: ``meal_type`` → ``mealType``, ``user_id`` → ``userId``.

    Args:
        field_name: The Pydantic field name in snake_case.

    Returns:
        The equivalent camelCase string.
    """
    return to_camel(field_name)


# ── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Payload for creating a new user account."""

    email: str
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    """Payload for authenticating an existing user."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """Authentication token pair returned after register or login."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    access_token: str
    refresh_token: str
    user_id: str


class RefreshRequest(BaseModel):
    """Payload for exchanging a refresh token for a new access token."""

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    refresh_token: str


# ── User Preferences ─────────────────────────────────────────────────────────

class PreferencesUpdate(BaseModel):
    """Partial update payload for user preferences (all fields optional).

    Only fields present in the request body are applied — ``None`` values
    are ignored, enabling partial-update (PATCH-style) semantics on a PUT
    endpoint.
    """

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    cuisine_preferences: Optional[list[str]] = None
    dietary_restrictions: Optional[list[str]] = None
    health_goal: Optional[str] = None
    time_preference: Optional[str] = None
    meal_prep: Optional[bool] = None
    cooking_equipment: Optional[list[str]] = None
    intolerances: Optional[list[str]] = None
    diet: Optional[str] = None
    perishable_optimization: Optional[bool] = None


class PreferencesResponse(BaseModel):
    """Full user preferences as returned by GET /api/user/preferences."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    cuisine_preferences: list[str]
    dietary_restrictions: list[str]
    health_goal: str
    time_preference: str
    meal_prep: bool
    cooking_equipment: list[str]
    intolerances: list[str] = []
    diet: Optional[str] = None
    perishable_optimization: bool
    updated_at: datetime


# ── VLM ──────────────────────────────────────────────────────────────────────

class IngredientItem(BaseModel):
    """A single ingredient detected by the vision model or entered manually.

    Attributes:
        name: Plain culinary name (brand names and qualifiers stripped).
        confidence: Detection confidence 0.0–1.0 (0.0 for manual entries).
        category: Freshness category — ``perishable``, ``semi-perishable``,
            ``shelf-stable``, or ``frozen``.
        urgency: Estimated days until spoilage (perishables only; ``None``
            for shelf-stable items). Used for urgency-boost scoring.
        estimated_quantity: Approximate amount detected in the given unit.
        unit: Unit of measure — ``pieces``, ``grams``, ``ml``, etc.
    """

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    name: str
    confidence: float = 0.0
    category: str = "shelf-stable"
    urgency: Optional[int] = None
    estimated_quantity: float = 1.0
    unit: str = "pieces"


class VlmResponse(BaseModel):
    """Response from the VLM ingredient identification endpoint."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    ingredients: list[IngredientItem]


# ── Recipe Pipeline ───────────────────────────────────────────────────────────

class SessionContextRequest(BaseModel):
    """Session context supplied by the user before starting a recipe session.

    This object is stored on the ``SessionPool`` row and replayed verbatim
    for every re-ideation round, so the LLM always has the original context.
    """

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    meal_type: str = "dinner"
    serving_count: int = 2
    available_time_minutes: int = 45
    available_prep_time_minutes: Optional[int] = None
    available_cook_time_minutes: Optional[int] = None
    occasion: Optional[str] = None
    available_ingredients: list[IngredientItem] = []


class RecommendRequest(BaseModel):
    """Request body for POST /api/recommend (start a new pipeline run)."""

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    user_id: str
    session_context: SessionContextRequest
    # Per-request ranking mode override — falls back to RANKING_MODE env var when None.
    # Accepted values: "hybrid" | "rules_only" | "llm_only"
    ranking_mode: Optional[str] = None


class RecipeOut(BaseModel):
    """A single recipe card returned by the recommendation pipeline.

    Includes both the core recipe fields scraped from the web and the
    ingredient-match metadata computed by the ranking service against the
    user's available ingredients.
    """

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    id: str
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

    # Ingredient-match metadata displayed on the recipe card in the UI.
    ingredient_match_pct: float = 0.0
    matched_ingredient_count: int = 0
    total_ingredient_count: int = 0
    missing_key_ingredients: list[str] = []
    swap_suggestions: list[dict] = []


class RecommendResponse(BaseModel):
    """Response from POST /api/recommend — contains the first recipe page."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    session_pool_id: str
    recipes: list[RecipeOut]
    pool_size: int
    shown_count: int
    # Recorded for observability — enables A/B comparison between ranking modes.
    ranking_mode_used: Optional[str] = None


class NextBatchResponse(BaseModel):
    """Response from GET /api/recommend/next — contains the next recipe page."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    recipes: list[RecipeOut]
    shown_count: int
    pool_size: int
    refetch_triggered: bool = False


class RerankRequest(BaseModel):
    """Request body for POST /api/rerank — signals a user preference."""

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    user_id: str
    session_pool_id: str
    liked_recipe_id: str
    action: str = "saved"


class RerankResponse(BaseModel):
    """Confirmation response from POST /api/rerank."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    message: str
    preference_inference: str


# ── History ───────────────────────────────────────────────────────────────────

class CookHistoryCreate(BaseModel):
    """Request body for logging a cooked recipe."""

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    recipe_id: str
    meal_type: str = ""
    serving_count: int = 2
    session_id: Optional[str] = None


class CookHistoryOut(BaseModel):
    """A single cooking history entry enriched with recipe display data."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    id: str
    recipe_id: str
    cooked_at: datetime
    meal_type: str
    serving_count: int
    session_id: Optional[str]
    # Enriched from recipe_cache for display in the History screen.
    recipe_title: Optional[str] = None
    recipe_image: Optional[str] = None
    recipe_cook_time: Optional[int] = None


# ── Saved ─────────────────────────────────────────────────────────────────────

class SaveRecipeRequest(BaseModel):
    """Request body for bookmarking a recipe."""

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    recipe_id: str


class SavedRecipeOut(BaseModel):
    """A single saved-recipe entry enriched with recipe display data."""

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    id: str
    recipe_id: str
    saved_at: datetime
    # Enriched from recipe_cache for display in the Saved screen.
    recipe_title: Optional[str] = None
    recipe_image: Optional[str] = None
    recipe_cook_time: Optional[int] = None


# ── Events ────────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    """Request body for recording a behavioral analytics event."""

    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)

    session_id: Optional[str] = None
    recipe_id: Optional[str] = None
    event_type: str
    metadata: dict = {}


# ── Generic ───────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standardized error response shape for all API error conditions.

    Machine-readable ``code`` field allows the frontend to branch on error
    type without string-matching on ``message``. ``retryable`` signals
    whether the frontend should offer an automatic retry.
    """

    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    code: str
    message: str
    retryable: bool = False
