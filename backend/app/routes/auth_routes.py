"""
Authentication routes: register, login, token refresh.

All three endpoints return a ``TokenResponse`` containing a short-lived access
token (1-day TTL) and a long-lived refresh token (30-day TTL). Tokens are
signed JWTs; the secret is configured via the ``JWT_SECRET`` environment
variable.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import User, UserPreferences
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _build_token_response(user: User) -> TokenResponse:
    """Create a full ``TokenResponse`` for a verified user.

    Args:
        user: The authenticated ``User`` ORM instance.

    Returns:
        ``TokenResponse`` with a fresh access token, refresh token, and user ID.
    """
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
    )


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account and return authentication tokens.

    Creates a ``User`` row and an empty ``UserPreferences`` row in a single
    transaction. Fails with 409 if the email address is already taken.

    Args:
        req: Registration payload containing ``email`` and ``password``.
        db: Async database session (injected by FastAPI).

    Returns:
        ``TokenResponse`` with access token, refresh token, and new user ID.

    Raises:
        HTTPException(409): If the email address is already registered.
    """
    duplicate_check = await db.execute(select(User).where(User.email == req.email))
    if duplicate_check.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = User(email=req.email, hashed_password=hash_password(req.password))
    db.add(new_user)
    await db.flush()  # Generate new_user.id before creating the preferences row.

    db.add(UserPreferences(user_id=new_user.id))
    await db.commit()
    await db.refresh(new_user)

    return _build_token_response(new_user)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return fresh tokens.

    Uses a timing-safe password comparison to prevent user enumeration. Both
    "email not found" and "wrong password" return the same 401 response.

    Args:
        req: Login payload containing ``email`` and ``password``.
        db: Async database session (injected by FastAPI).

    Returns:
        ``TokenResponse`` with fresh access and refresh tokens.

    Raises:
        HTTPException(401): If the email is not found or the password is wrong.
    """
    user_result = await db.execute(select(User).where(User.email == req.email))
    user = user_result.scalar_one_or_none()

    # Deliberate single message for both "not found" and "wrong password"
    # to prevent user-enumeration attacks.
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return _build_token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token and refresh token.

    The existing refresh token is validated and decoded to extract the user ID.
    Both tokens are rotated on each call (token rotation pattern).

    Args:
        req: Refresh payload containing the ``refresh_token`` string.
        db: Async database session (injected by FastAPI).

    Returns:
        ``TokenResponse`` with a new access token and rotated refresh token.

    Raises:
        HTTPException(401): If the refresh token is invalid or the user no
            longer exists.
    """
    user_id = decode_token(req.refresh_token)

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return _build_token_response(user)
