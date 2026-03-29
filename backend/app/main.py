"""
Smart Recipe Planner - Backend API entry point.
"""

import logging
import time
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import CORS_ORIGINS, LLM_BASE_URL, VLM_BASE_URL, SERPAPI_KEY, WEB_RECIPE_SITES
from app.database import init_db
from app.routes import (
    auth_routes, user_routes, vlm_routes,
    recommend_routes, history_routes, saved_routes, event_routes,
    recipe_routes,
)

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting up — initializing database")
    await init_db()
    logger.info("Database ready")

    # -----------------------------------------------------------------------
    # Startup configuration summary — makes it immediately obvious which
    # external services are live vs. running in mock/fallback mode.
    # -----------------------------------------------------------------------
    # Web recipe fetcher — always active; SerpAPI is optional
    if SERPAPI_KEY:
        logger.info("Recipe fetcher: web mode with SerpAPI ✓ (sites: %s)", WEB_RECIPE_SITES)
    else:
        logger.info(
            "Recipe fetcher: web mode via DuckDuckGo (free, no key) — "
            "set SERPAPI_KEY in .env for higher-reliability Google-backed search. "
            "Sites: %s", WEB_RECIPE_SITES
        )

    if not LLM_BASE_URL:
        logger.warning(
            "LLM_BASE_URL is not set — LLM ideation is DISABLED. "
            "Recipe suggestions will fall back to generic keyword list."
        )
    else:
        logger.info("LLM: %s at %s ✓", "(see LLM_MODEL)", LLM_BASE_URL)

    if not VLM_BASE_URL:
        logger.warning(
            "VLM_BASE_URL is not set — ingredient scanning will use MOCK ingredients."
        )
    else:
        logger.info("VLM: configured at %s ✓", VLM_BASE_URL)

    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Smart Recipe Planner API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url.path, "".join(tb))
    return JSONResponse(status_code=500, content={"error": {
        "code": "ERR_INTERNAL",
        "message": "An unexpected error occurred. Please try again.",
        "retryable": True,
    }})


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d (%.0fms)",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(vlm_routes.router)
app.include_router(recommend_routes.router)
app.include_router(history_routes.router)
app.include_router(saved_routes.router)
app.include_router(event_routes.router)
app.include_router(recipe_routes.router)


@app.get("/api/health")
async def health_check():
    """NFR-OBS-02: Health check with dependency status."""
    from app.config import VLM_BASE_URL, LLM_BASE_URL, SERPAPI_KEY
    from app.database import engine as db_engine
    import httpx

    deps = {}

    # DB check
    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        deps["db"] = "ok"
    except Exception:
        deps["db"] = "down"

    # VLM check
    if VLM_BASE_URL:
        try:
            ollama_root = VLM_BASE_URL.rstrip("/")
            if ollama_root.endswith("/v1"):
                ollama_root = ollama_root[:-3]
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{ollama_root}/api/tags")
                deps["vlm"] = "ok" if r.status_code == 200 else "degraded"
        except Exception:
            deps["vlm"] = "down"
    else:
        deps["vlm"] = "mock"

    # LLM check
    if LLM_BASE_URL:
        try:
            ollama_root = LLM_BASE_URL.rstrip("/")
            if ollama_root.endswith("/v1"):
                ollama_root = ollama_root[:-3]
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{ollama_root}/api/tags")
                deps["llm"] = "ok" if r.status_code == 200 else "degraded"
        except Exception:
            deps["llm"] = "down"
    else:
        deps["llm"] = "mock"

    # Web recipe fetcher — always active; SerpAPI enhances reliability
    deps["recipe_fetcher"] = "serpapi" if SERPAPI_KEY else "duckduckgo"

    all_vals = list(deps.values())
    if all(v in ("ok", "mock") for v in all_vals):
        overall = "ok"
    elif "down" in all_vals:
        overall = "degraded"
    else:
        overall = "degraded"

    return {"status": overall, "dependencies": deps}
