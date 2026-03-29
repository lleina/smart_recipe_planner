#!/usr/bin/env python3
"""
Seed script — populates RecipeCache with real Spoonacular recipes.

Run ONCE before your demo to fill the local cache. After seeding, all
pipeline runs will be served from cache at zero credit cost, no matter
how many sessions you run or how diverse the LLM suggestions are.

Estimated credit cost (complexSearch w/ addRecipeInformation=true):
  ~2 credits per result × (number per query) × (number of queries)
  Default: 2 × 5 × 14 queries = ~140 credits total for ~70 recipes.

Usage:
  cd backend
  venv/bin/python scripts/seed_cache.py [--dry-run]

Options:
  --dry-run   Print what would be fetched without calling the API or the DB.

Requires SPOONACULAR_API_KEY in backend/.env.
"""

import argparse
import asyncio
import logging
import sys
import os

# Allow running from backend/ root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import SPOONACULAR_API_KEY, SPOONACULAR_BASE_URL, DATABASE_URL
from app.models import Base, RecipeCache
from app.services.spoonacular_client import _spoonacular_to_dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed")

# ---------------------------------------------------------------------------
# Search queries — chosen to cover most demo ingredient combinations.
# Tweak freely. Each query fetches RESULTS_PER_QUERY recipes.
# ---------------------------------------------------------------------------
SEED_QUERIES = [
    # Proteins
    "chicken dinner easy",
    "beef stir fry",
    "salmon fillet healthy",
    "shrimp pasta",
    "ground beef tacos",
    "tofu vegetarian",
    # Pantry staples
    "pasta tomato sauce",
    "fried rice egg",
    "vegetable soup",
    "chickpea curry",
    # Quick meals
    "15 minute dinner easy",
    "sheet pan chicken vegetables",
    # International
    "korean bibimbap",
    "thai green curry",
]

RESULTS_PER_QUERY = 5  # Spoonacular max useful free-tier per call
TOTAL_ESTIMATED_CREDITS = len(SEED_QUERIES) * RESULTS_PER_QUERY * 2


async def fetch_and_cache(
    query: str,
    session: AsyncSession,
    dry_run: bool,
) -> int:
    """Fetches up to RESULTS_PER_QUERY recipes for a query and upserts them."""
    if dry_run:
        logger.info("[DRY RUN] Would search: '%s' (up to %d results)", query, RESULTS_PER_QUERY)
        return 0

    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "query": query,
        "number": RESULTS_PER_QUERY,
        "addRecipeInformation": "true",
        "fillIngredients": "true",
        "instructionsRequired": "true",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SPOONACULAR_BASE_URL}/recipes/complexSearch", params=params
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    stored = 0
    for raw in results:
        try:
            d = _spoonacular_to_dict(raw)
            rc = RecipeCache(
                id=f"sp-{raw['id']}",
                spoonacular_id=str(raw["id"]),
                title=d["title"],
                description=d.get("description", ""),
                image=d.get("image", ""),
                prep_time=d.get("prep_time", 0),
                cook_time=d.get("cook_time", 0),
                total_time=d.get("total_time", 0),
                difficulty=d.get("difficulty", "medium"),
                servings=d.get("servings", 4),
                cuisine=d.get("cuisine", ""),
                meal_type=d.get("meal_type", []),
                occasions=d.get("occasions", []),
                rating=d.get("rating", 0.0),
                source="spoonacular",
                source_url=d.get("source_url", ""),
                cooking_equipment=[],
                ingredients=d.get("ingredients", []),
                instructions=d.get("instructions", []),
            )
            await session.merge(rc)
            stored += 1
            logger.info("  + %-50s [sp:%s]", d["title"][:50], raw["id"])
        except Exception as exc:
            logger.warning("  ! Failed to store recipe %s: %s", raw.get("id"), exc)

    await session.commit()
    return stored


async def main(dry_run: bool) -> None:
    if not SPOONACULAR_API_KEY:
        logger.error("SPOONACULAR_API_KEY is not set in .env — cannot seed.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Recipe cache seed script")
    logger.info("Queries:             %d", len(SEED_QUERIES))
    logger.info("Results per query:   %d", RESULTS_PER_QUERY)
    logger.info("Est. credits needed: ~%d", TOTAL_ESTIMATED_CREDITS)
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN MODE — no API calls will be made\n")

    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_stored = 0
    credits_spent = 0

    async with AsyncSessionLocal() as session:
        for i, query in enumerate(SEED_QUERIES, 1):
            logger.info("[%d/%d] Query: '%s'", i, len(SEED_QUERIES), query)
            try:
                stored = await fetch_and_cache(query, session, dry_run)
                total_stored += stored
                if not dry_run:
                    credits_spent += stored * 2
                    logger.info(
                        "  Stored %d recipe(s) | running credits: ~%d",
                        stored, credits_spent,
                    )
                # Small delay to be polite to the API
                if not dry_run and i < len(SEED_QUERIES):
                    await asyncio.sleep(0.5)
            except httpx.HTTPStatusError as exc:
                logger.error("  HTTP %d for '%s': %s", exc.response.status_code, query, exc)
            except Exception as exc:
                logger.error("  Unexpected error for '%s': %s", query, exc)

    await engine.dispose()

    logger.info("=" * 60)
    if dry_run:
        logger.info("DRY RUN complete — no changes made.")
        logger.info("Remove --dry-run to actually seed the cache (~%d credits).", TOTAL_ESTIMATED_CREDITS)
    else:
        logger.info("Seeding complete!")
        logger.info("  Recipes stored/updated: %d", total_stored)
        logger.info("  Approximate credits used: ~%d", credits_spent)
        logger.info("  Future pipeline runs will served from cache: 0 credits.")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed RecipeCache from Spoonacular")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be fetched without calling the API",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
