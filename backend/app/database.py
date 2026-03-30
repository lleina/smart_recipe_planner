"""
Database engine and async session management.

Creates a single SQLAlchemy async engine shared across the application lifetime.
The ``async_session`` factory is used both by FastAPI's ``get_db`` dependency
(request-scoped sessions) and directly in background tasks that need their own
session after the originating request has closed.

Schema evolution is handled by ``_apply_schema_migrations``, which uses
SQLite PRAGMA to detect missing columns and applies ``ALTER TABLE`` statements
incrementally. This approach avoids a full migration framework for the current
simple schema while keeping the database in sync with the ORM models.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)

# Shared session factory — used by get_db and by background task helpers that
# create their own sessions (since request sessions close before tasks run).
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """Yield an async database session for use as a FastAPI dependency.

    The session is automatically closed after the request completes (or after
    an exception is raised) because it is used as a context manager internally.

    Yields:
        ``AsyncSession``: An open database session scoped to the current request.
    """
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create all tables and apply incremental schema migrations on startup.

    Safe to call on every startup — ``create_all`` is a no-op for tables that
    already exist, and the migration function skips columns that are already
    present.
    """
    from app.models import Base  # pylint: disable=import-outside-toplevel

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _apply_schema_migrations(connection)


async def _apply_schema_migrations(connection) -> None:
    """Apply incremental column additions for schema evolution.

    SQLite does not support ``DROP COLUMN`` or ``ALTER COLUMN``, so schema
    changes are limited to adding new columns. Each migration step inspects
    the live schema via PRAGMA before executing the ALTER statement to make
    this function idempotent — safe to run on every startup.

    Args:
        connection: An active ``AsyncConnection`` within a transaction.
    """
    # ── user_preferences migrations ─────────────────────────────────────────
    user_prefs_schema_result = await connection.execute(
        text("PRAGMA table_info(user_preferences)")
    )
    existing_user_prefs_columns = {row[1] for row in user_prefs_schema_result.fetchall()}

    if "intolerances" not in existing_user_prefs_columns:
        await connection.execute(
            text("ALTER TABLE user_preferences ADD COLUMN intolerances JSON DEFAULT '[]'")
        )

    if "diet" not in existing_user_prefs_columns:
        await connection.execute(
            text("ALTER TABLE user_preferences ADD COLUMN diet VARCHAR DEFAULT NULL")
        )

    # ── session_pool migrations ─────────────────────────────────────────────
    session_pool_schema_result = await connection.execute(
        text("PRAGMA table_info(session_pool)")
    )
    existing_session_pool_columns = {
        row[1] for row in session_pool_schema_result.fetchall()
    }

    if "session_context" not in existing_session_pool_columns:
        await connection.execute(
            text("ALTER TABLE session_pool ADD COLUMN session_context JSON DEFAULT NULL")
        )
