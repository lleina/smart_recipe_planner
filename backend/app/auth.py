"""
JWT authentication utilities for the Smart Recipe Planner API.

Provides password hashing, JWT creation and decoding, and a FastAPI dependency
(``get_current_user_id``) that extracts and validates the Bearer token on every
protected request.

Token types:
    access  — Short-lived (configurable via JWT_EXPIRY_MINUTES, default 24 h).
              Sent as a Bearer token on every API request.
    refresh — Long-lived (configurable via JWT_REFRESH_EXPIRY_DAYS, default 30 d).
              Used only on the /auth/refresh endpoint to obtain a new access token.
"""

import bcrypt
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import (
    JWT_ALGORITHM,
    JWT_EXPIRY_MINUTES,
    JWT_REFRESH_EXPIRY_DAYS,
    JWT_SECRET,
)

_bearer_scheme = HTTPBearer()


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt.

    The salt is randomly generated per call, so the same password produces
    a different hash each time — this is the expected bcrypt behaviour.

    Args:
        plain_password: The user's raw password string.

    Returns:
        A bcrypt hash string suitable for storage in the database.
    """
    return bcrypt.hashpw(
        plain_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    Uses a timing-safe comparison internally — safe against timing attacks.

    Args:
        plain_password: The raw password supplied by the user at login.
        hashed_password: The bcrypt hash retrieved from the database.

    Returns:
        ``True`` if the password matches; ``False`` otherwise.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token for the given user.

    Args:
        user_id: The user's UUID primary key (stored as the ``sub`` claim).

    Returns:
        A signed JWT string. Expires after ``JWT_EXPIRY_MINUTES`` minutes.
    """
    expiry = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRY_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expiry},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived JWT refresh token for the given user.

    Refresh tokens carry a ``type: refresh`` claim to distinguish them from
    access tokens — this prevents using a refresh token as an access token.

    Args:
        user_id: The user's UUID primary key (stored as the ``sub`` claim).

    Returns:
        A signed JWT string. Expires after ``JWT_REFRESH_EXPIRY_DAYS`` days.
    """
    expiry = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRY_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expiry, "type": "refresh"},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> str:
    """Decode a JWT token and return the encoded user ID.

    Args:
        token: The raw JWT string (without the ``Bearer `` prefix).

    Returns:
        The user ID string extracted from the ``sub`` claim.

    Raises:
        HTTPException(401): If the token is malformed, expired, or missing the
            ``sub`` claim.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token: missing subject")
        return user_id
    except JWTError as exc:
        raise HTTPException(
            status_code=401, detail="Invalid or expired token"
        ) from exc


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency that extracts the authenticated user ID from the Bearer token.

    Inject this into any route handler that requires authentication:

        @router.get("/protected")
        async def protected_route(user_id: str = Depends(get_current_user_id)):
            ...

    Args:
        credentials: HTTP Bearer credentials extracted by FastAPI's security scheme.

    Returns:
        The authenticated user's UUID string.

    Raises:
        HTTPException(401): If the Bearer token is absent, malformed, or expired.
    """
    return decode_token(credentials.credentials)
