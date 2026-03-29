"""
Database engine and session management.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


async def _migrate(conn):
    """
    Run lightweight column additions for schema evolution.
    SQLite requires individual ALTER TABLE statements; we skip if the column
    already exists by inspecting PRAGMA table_info first.
    """
    result = await conn.execute(text("PRAGMA table_info(user_preferences)"))
    existing_columns = {row[1] for row in result.fetchall()}

    if "intolerances" not in existing_columns:
        await conn.execute(
            text("ALTER TABLE user_preferences ADD COLUMN intolerances JSON DEFAULT '[]'")
        )

    if "diet" not in existing_columns:
        await conn.execute(
            text("ALTER TABLE user_preferences ADD COLUMN diet VARCHAR DEFAULT NULL")
        )
