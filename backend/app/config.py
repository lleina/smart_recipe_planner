"""
Application configuration loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data.db")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60 * 24
JWT_REFRESH_EXPIRY_DAYS = 30

# ---------------------------------------------------------------------------
# Web recipe fetcher configuration
# Stage 3 uses DuckDuckGo search (free, no key) + recipe-scrapers to fetch
# real recipes from quality cooking sites. SerpAPI is optional for higher
# reliability at scale (set SERPAPI_KEY to enable).
# ---------------------------------------------------------------------------

# Optional: SerpAPI key for Google-backed search (more reliable than DuckDuckGo).
# Leave empty to use DuckDuckGo for free.
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

# Per-URL HTTP timeout in seconds for recipe scraping.
WEB_RECIPE_TIMEOUT = int(os.getenv("WEB_RECIPE_TIMEOUT", "10"))

# Space-separated list of cooking site domains to target in web searches.
# recipe-scrapers supports all of these with structured data extraction.
WEB_RECIPE_SITES = os.getenv(
    "WEB_RECIPE_SITES",
    "budgetbytes.com recipetineats.com skinnytaste.com tasty.co cookingclassy.com "
    "cafedelites.com therecipecritic.com natashaskitchen.com gimmesomeoven.com "
    "damndelicious.net halfbakedharvest.com iwashyoudry.com"
)

# ---------------------------------------------------------------------------
# VLM configuration (ingredient recognition)
# Recommended local backend: Ollama + qwen3-vl:4b
# Set VLM_BASE_URL to your self-hosted OpenAI-compatible endpoint, e.g.:
#   Ollama:  http://localhost:11434/v1
#   vLLM:    http://localhost:8001/v1
# Leave empty to use mock data in development (no Ollama required).
# ---------------------------------------------------------------------------
VLM_BASE_URL = os.getenv("VLM_BASE_URL", "")
VLM_MODEL = os.getenv("VLM_MODEL", "qwen3-vl:4b")
VLM_API_KEY = os.getenv("VLM_API_KEY", "local")
VLM_TIMEOUT_SECONDS = int(os.getenv("VLM_TIMEOUT_SECONDS", "120"))

# ---------------------------------------------------------------------------
# LLM configuration (ideation + re-ranking)
# Recommended local backend: Ollama + qwen3:4b (runs on ~3 GB VRAM / CPU)
# Set LLM_BASE_URL to your self-hosted OpenAI-compatible endpoint.
# Leave empty to skip LLM steps and use keyword fallback logic.
# ---------------------------------------------------------------------------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:4b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "local")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

# ---------------------------------------------------------------------------
# Ranking mode: controls pipeline ranking behaviour.
# Options:
#   hybrid     - rule scorer + LLM re-ranker on top 15 (default)
#   rules_only - deterministic scorer only, no LLM call
#   llm_only   - pass all candidates directly to LLM
# Can be overridden per-request via RecommendRequest.ranking_mode.
# ---------------------------------------------------------------------------
RANKING_MODE = os.getenv("RANKING_MODE", "hybrid")

CORS_ORIGINS = ["*"]
