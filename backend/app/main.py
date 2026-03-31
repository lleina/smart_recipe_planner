"""
Smart Recipe Planner — Backend API entry point.

Responsibilities:
    - FastAPI application factory and lifecycle management (``lifespan``).
    - Global exception handler with structured JSON error responses.
    - HTTP request logging middleware (method, path, status, latency).
    - CORS middleware configuration.
    - Router registration for all API route modules.
    - Health check endpoint at GET /api/health.

Startup sequence:
    1. Initialize the database (create tables + apply migrations).
    2. Log the active configuration for LLM, VLM, and recipe fetcher.
    3. Begin serving requests.
"""

import logging
import os
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import (
    CORS_ORIGINS,
    LLM_BASE_URL,
    SERPAPI_KEY,
    VLM_BASE_URL,
    WEB_RECIPE_SITES,
)
from app.database import engine as db_engine, init_db
from app.routes import (
    auth_routes,
    event_routes,
    history_routes,
    recipe_routes,
    recommend_routes,
    saved_routes,
    user_routes,
    vlm_routes,
)

# ---------------------------------------------------------------------------
# Structured logging — format is consistent across all app.* loggers.
# Per-restart log file in backend/logs/ for debugging pipeline flow.
# ---------------------------------------------------------------------------
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Console handler
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
_console.setLevel(logging.INFO)

# File handler — one file per restart, capped at 20 MB
_file = RotatingFileHandler(_LOG_FILE, maxBytes=20_000_000, backupCount=1)
_file.setFormatter(_fmt)
_file.setLevel(logging.DEBUG)  # capture DEBUG in file for detailed tracing

logging.basicConfig(level=logging.DEBUG, handlers=[_console, _file])
logger = logging.getLogger("app")
logger.info("=" * 70)
logger.info("NEW APP SESSION — log file: %s", _LOG_FILE)
logger.info("=" * 70)


@asynccontextmanager
async def _application_lifespan(application: FastAPI):
    """Manage startup and shutdown tasks for the FastAPI application.

    On startup: initialize the database and log the active configuration.
    On shutdown: log the shutdown event (engine cleanup handled by SQLAlchemy).

    Args:
        application: The FastAPI application instance (unused; required by API).
    """
    logger.info("Starting up — initializing database")
    await init_db()
    logger.info("Database ready")

    # Log active configuration so engineers can confirm the right services
    # are live vs. running in mock/fallback mode on startup.
    if SERPAPI_KEY:
        logger.info(
            "Recipe fetcher: web mode with SerpAPI ✓ (sites: %s)", WEB_RECIPE_SITES
        )
    else:
        logger.info(
            "Recipe fetcher: DuckDuckGo (free, no API key) — "
            "set SERPAPI_KEY for higher-reliability Google-backed search. "
            "Sites: %s",
            WEB_RECIPE_SITES,
        )

    if LLM_BASE_URL:
        logger.info("LLM configured at %s ✓", LLM_BASE_URL)
    else:
        logger.warning(
            "LLM_BASE_URL is not set — LLM ideation disabled; "
            "recipe suggestions will use a keyword fallback list."
        )

    if VLM_BASE_URL:
        logger.info("VLM configured at %s ✓", VLM_BASE_URL)
    else:
        logger.warning(
            "VLM_BASE_URL is not set — ingredient scanning will use mock data."
        )

    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Smart Recipe Planner API",
    version="0.1.0",
    lifespan=_application_lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch any unhandled exception and return a standardized 500 JSON error.

    Logs the full traceback at ERROR level so issues are visible in server
    logs without exposing stack traces to the client.

    Args:
        request: The HTTP request that triggered the exception.
        exc: The unhandled exception.

    Returns:
        A JSON response with a standardized error shape and HTTP 500 status.
    """
    formatted_traceback = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    logger.error(
        "Unhandled exception on %s %s:\n%s",
        request.method,
        request.url.path,
        formatted_traceback,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "ERR_INTERNAL",
                "message": "An unexpected error occurred. Please try again.",
                "retryable": True,
            }
        },
    )


@app.middleware("http")
async def log_every_request(request: Request, call_next):
    """Log the method, path, status code, and latency for every HTTP request.

    Args:
        request: Incoming HTTP request.
        call_next: Next middleware or route handler in the chain.

    Returns:
        The HTTP response from the route handler.
    """
    request_start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - request_start) * 1000
    logger.info(
        "%s %s → %d (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
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


def _check_ollama_reachability(base_url: str) -> str:
    """Return the Ollama API root URL derived from an OpenAI-compatible base URL.

    Strips the trailing ``/v1`` segment (if present) to produce the Ollama
    root from which ``/api/tags`` can be queried for health checks.

    Args:
        base_url: The configured endpoint URL (e.g. ``http://localhost:11434/v1``).

    Returns:
        The Ollama root URL (e.g. ``http://localhost:11434``).
    """
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root


@app.get("/api/health")
async def health_check() -> dict:
    """Return service health and dependency status.

    Probes the database, VLM endpoint, and LLM endpoint with short timeouts
    and aggregates the results into a single health status. Useful for
    monitoring and for the startup log to confirm all services are live.

    Returns:
        Dict with ``status`` (``"ok"`` or ``"degraded"``) and a
        ``dependencies`` dict mapping each service name to its status string
        (``"ok"``, ``"degraded"``, ``"down"``, or ``"mock"``).
    """
    dependency_status: dict[str, str] = {}

    # Database health — a simple SELECT 1 confirms the connection is alive.
    try:
        async with db_engine.connect() as db_connection:
            await db_connection.execute(text("SELECT 1"))
        dependency_status["db"] = "ok"
    except Exception:  # pylint: disable=broad-except
        dependency_status["db"] = "down"

    # VLM health — query Ollama's /api/tags endpoint with a 3-second timeout.
    if VLM_BASE_URL:
        try:
            ollama_root = _check_ollama_reachability(VLM_BASE_URL)
            async with httpx.AsyncClient(timeout=3) as http_client:
                response = await http_client.get(f"{ollama_root}/api/tags")
            dependency_status["vlm"] = "ok" if response.status_code == 200 else "degraded"
        except Exception:  # pylint: disable=broad-except
            dependency_status["vlm"] = "down"
    else:
        dependency_status["vlm"] = "mock"

    # LLM health — same approach as VLM.
    if LLM_BASE_URL:
        try:
            ollama_root = _check_ollama_reachability(LLM_BASE_URL)
            async with httpx.AsyncClient(timeout=3) as http_client:
                response = await http_client.get(f"{ollama_root}/api/tags")
            dependency_status["llm"] = "ok" if response.status_code == 200 else "degraded"
        except Exception:  # pylint: disable=broad-except
            dependency_status["llm"] = "down"
    else:
        dependency_status["llm"] = "mock"

    # Recipe fetcher is always active; SerpAPI availability is informational.
    dependency_status["recipe_fetcher"] = "serpapi" if SERPAPI_KEY else "duckduckgo"

    all_status_values = list(dependency_status.values())
    if all(status in ("ok", "mock", "duckduckgo", "serpapi") for status in all_status_values):
        overall_status = "ok"
    else:
        overall_status = "degraded"

    return {"status": overall_status, "dependencies": dependency_status}
