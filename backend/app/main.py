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
from app.config import CORS_ORIGINS
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
    return JSONResponse(status_code=500, content={"error": str(exc)})


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
    return {"status": "ok"}
