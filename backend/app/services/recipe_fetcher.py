"""
Recipe fetcher — Stage 3 of the pipeline.

Flow per LLM suggestion:
  1. Cache check  — title-similarity match against RecipeCache (free, instant)
  2. Web search   — DuckDuckGo (free, no key, runs in thread executor) or SerpAPI
                    → top cooking-site URL → recipe-scrapers extracts structured data
  3. Skip         — if both cache and web fail, the suggestion is dropped
                    (the LLM generates 40 suggestions; partial success is fine)

All 40 suggestions are resolved concurrently via asyncio.gather with a semaphore
to avoid overwhelming the search engine. DuckDuckGo's synchronous client runs in
a thread-pool executor so it never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from recipe_scrapers import scrape_html
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    SERPAPI_KEY,
    WEB_RECIPE_TIMEOUT,
    WEB_RECIPE_SITES,
)
from app.models import RecipeCache
from app.schemas import SessionContextRequest

logger = logging.getLogger("app.recipe_fetcher")

# ---------------------------------------------------------------------------
# Concurrency limits
# ---------------------------------------------------------------------------
# Search: keep low to avoid DDG rate-limiting (5 concurrent searches max)
_SEARCH_SEM = asyncio.Semaphore(8)
# Scrape: HTTP I/O bound — more parallelism is fine
_SCRAPE_SEM = asyncio.Semaphore(15)

# Thread pool for running the synchronous ddgs client
_THREAD_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ddg")

# ---------------------------------------------------------------------------
# Target cooking sites
# A wide list improves variety. We rotate subsets for site-filtered queries
# to avoid overly long OR chains (which confuse search engines).
# ---------------------------------------------------------------------------
_ALL_SITES = [s.strip() for s in WEB_RECIPE_SITES.split() if s.strip()]

# Counter used to rotate which sites appear in the site: filter query
_site_rotation_counter = 0
_SITES_PER_QUERY = 6  # number of site: filters per targeted query


def _get_rotated_sites() -> list[str]:
    """Return a rotating subset of _ALL_SITES for the next query."""
    global _site_rotation_counter
    if len(_ALL_SITES) <= _SITES_PER_QUERY:
        return _ALL_SITES
    start = (_site_rotation_counter * _SITES_PER_QUERY) % len(_ALL_SITES)
    _site_rotation_counter += 1
    # Wrap around if needed
    sites = _ALL_SITES[start:start + _SITES_PER_QUERY]
    if len(sites) < _SITES_PER_QUERY:
        sites += _ALL_SITES[:_SITES_PER_QUERY - len(sites)]
    return sites

# ---------------------------------------------------------------------------
# Ingredient string parser
# ---------------------------------------------------------------------------
_FRACTION_MAP = {"½": 0.5, "⅓": 0.333, "¼": 0.25, "¾": 0.75, "⅔": 0.667, "⅛": 0.125}
_UNIT_RE = re.compile(
    r"^(cups?|tbsp|tbs|tablespoons?|tsp|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|"
    r"ml|liters?|litres?|quarts?|qt|pints?|pt|gallons?|gal|cloves?|stalks?|"
    r"cans?|jars?|bags?|bunches?|heads?|slices?|pieces?|fillets?|strips?|"
    r"pinch(?:es)?|dash(?:es)?|handful|handfuls?|sprigs?|leaves?|sheets?)\b",
    re.IGNORECASE,
)


def _parse_ingredient(raw: str) -> dict:
    """Parse a raw ingredient string into {quantity, unit, name}."""
    s = raw.strip()
    for frac, val in _FRACTION_MAP.items():
        s = s.replace(frac, str(val))
    qty = 1.0
    m = re.match(r"^(\d+)\s+(\d+/\d+)\s*", s)
    if m:
        qty = float(m.group(1)) + eval(m.group(2))  # noqa: S307
        s = s[m.end():]
    else:
        m = re.match(r"^(\d+/\d+)\s*", s)
        if m:
            num, den = m.group(1).split("/")
            qty = float(num) / float(den)
            s = s[m.end():]
        else:
            m = re.match(r"^(\d+(?:\.\d+)?)\s*", s)
            if m and m.group(0).strip():
                qty = float(m.group(1))
                s = s[m.end():]
    unit = ""
    unit_match = _UNIT_RE.match(s)
    if unit_match:
        unit = unit_match.group(0).lower()
        s = s[unit_match.end():].strip()
    name = re.split(r",\s*", s)[0].strip().lower()
    name = re.sub(
        r"^(fresh|frozen|dried|canned|cooked|raw|boneless|skinless|chopped|"
        r"minced|diced|sliced|grated|shredded|large|small|medium|ripe|"
        r"peeled|trimmed|halved|quartered)\s+",
        "", name, flags=re.IGNORECASE,
    )
    return {"quantity": qty, "unit": unit or "as needed", "name": name or raw.strip().lower()}


def _split_instructions(raw: str) -> list[dict]:
    """
    Split a block of instruction text into clean, numbered step dicts.
    Handles multiple formats: numbered lists, paragraph blocks, run-on text.
    Merges very short steps and cleans up formatting artifacts.
    """
    if not raw:
        return []

    text = raw.strip()

    # First, try explicit numbered steps (most structured format)
    numbered = re.split(r"\n+(?=\d+[\.\)]\s|Step\s+\d+)", text, flags=re.IGNORECASE)
    was_structured = False
    if len(numbered) > 1:
        steps = numbered
        was_structured = True
    else:
        # Try double-newline separation
        para_split = [s.strip() for s in re.split(r"\n{2,}", text) if s.strip()]
        if len(para_split) > 1:
            steps = para_split
            was_structured = True
        else:
            # Fall back to sentence-based splitting for run-on text
            # Split on period followed by space and capital letter (new sentence)
            sentences = re.split(r'(?<=[.!])\s+(?=[A-Z])', text)
            if len(sentences) > 1:
                steps = sentences
            else:
                steps = [text]

    cleaned = []
    for text_chunk in steps:
        # Remove step number prefixes
        t = re.sub(r"^\d+[\.\)]\s*|^Step\s+\d+[:\.]?\s*", "", text_chunk, flags=re.IGNORECASE).strip()
        # Remove stray bullet points
        t = re.sub(r"^[•\-\*]\s*", "", t).strip()
        # Collapse whitespace
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        cleaned.append(t)

    # Only merge very short steps when they came from sentence-splitting (run-on text),
    # NOT when steps were already explicitly numbered/structured by the source
    merged = cleaned
    if not was_structured:
        merged = []
        i = 0
        while i < len(cleaned):
            current = cleaned[i]
            # If current step is very short and not the last, merge with next
            if len(current) < 30 and i + 1 < len(cleaned) and not current.endswith('.'):
                merged.append(current + '. ' + cleaned[i + 1])
                i += 2
            else:
                merged.append(current)
                i += 1

    # Ensure each step ends with proper punctuation
    result = []
    for idx, step_text in enumerate(merged, 1):
        if step_text and not step_text[-1] in '.!?':
            step_text += '.'
        result.append({"step": idx, "text": step_text, "image": None})

    return result or [{"step": 1, "text": raw.strip(), "image": None}]


def _difficulty_from_time(total_minutes: int) -> str:
    if total_minutes <= 20:
        return "easy"
    if total_minutes <= 45:
        return "medium"
    return "hard"


def _recipe_id_from_url(url: str) -> str:
    return "web-" + hashlib.md5(url.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Description sanitizer — remove web-scraping artifacts
# ---------------------------------------------------------------------------
_DESC_JUNK_PATTERNS = [
    # References to page UI elements
    re.compile(r"\b(recipe\s+)?video\s+(above|below|here)\b", re.IGNORECASE),
    re.compile(r"\bwatch\s+(the\s+)?(video|clip|tutorial)\b", re.IGNORECASE),
    re.compile(r"\bscroll\s+(down|up|below)\b", re.IGNORECASE),
    re.compile(r"\bclick\s+(here|below|above|the\s+link)\b", re.IGNORECASE),
    re.compile(r"\btap\s+(here|below|above|the)\b", re.IGNORECASE),
    re.compile(r"\bjump\s+to\s+recipe\b", re.IGNORECASE),
    re.compile(r"\bprint\s+recipe\b", re.IGNORECASE),
    re.compile(r"\bsee\s+(the\s+)?recipe\s+card\s+(below|above)\b", re.IGNORECASE),
    re.compile(r"\brecipe\s+card\s+(below|above)\b", re.IGNORECASE),
    re.compile(r"\bpin\s+(this|it)\b", re.IGNORECASE),
    re.compile(r"\bshare\s+(this|it)\s+(on|via)\b", re.IGNORECASE),
    re.compile(r"\b(leave|post)\s+a\s+comment\b", re.IGNORECASE),
    re.compile(r"\bsign\s+up\s+(for|to)\b", re.IGNORECASE),
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\bnewsletter\b", re.IGNORECASE),
    re.compile(r"\baffiliate\s+link", re.IGNORECASE),
    re.compile(r"\bsponsored\s+post\b", re.IGNORECASE),
    re.compile(r"\bphoto\s+(above|below|credit)\b", re.IGNORECASE),
    re.compile(r"\bimage\s+(above|below|credit)\b", re.IGNORECASE),
    re.compile(r"\bas\s+an?\s+amazon\s+associate\b", re.IGNORECASE),
]


def _clean_description(description: str, title: str = "") -> str:
    """
    Remove web-scraping artifacts from a recipe description.
    If the cleaned result is too short, generate a simple description from the title.
    """
    if not description:
        return f"A delicious {title}." if title else ""

    text = description.strip()

    # Remove sentences that contain junk patterns
    sentences = re.split(r'(?<=[.!?])\s+', text)
    clean_sentences = []
    for sentence in sentences:
        if any(pat.search(sentence) for pat in _DESC_JUNK_PATTERNS):
            continue
        clean_sentences.append(sentence)

    cleaned = " ".join(clean_sentences).strip()

    # If cleaning removed too much, fall back to title-based description
    if len(cleaned) < 20:
        return f"A delicious {title}." if title else ""

    # Truncate overly long descriptions (max ~300 chars)
    if len(cleaned) > 300:
        cut = cleaned[:297].rsplit(" ", 1)[0]
        cleaned = cut.rstrip(".,!?;:") + "..."

    return cleaned


# ---------------------------------------------------------------------------
# Title similarity (Jaccard on cleaned token sets)
# ---------------------------------------------------------------------------
_STOPWORDS = {
    # Marketing fluff (stripped for matching)
    "easy", "quick", "simple", "best", "homemade", "classic", "the", "a", "an",
    "with", "and", "or", "for", "of", "in", "on", "my", "your", "how", "to",
    "make", "recipe", "recipes", "style", "inspired",
    # Culinary descriptors (stripped for cache matching — "Creamy X" still matches "X")
    "creamy", "crispy", "spicy", "smoky", "smokey", "buttery", "cheesy",
    "hearty", "chunky", "fluffy", "tangy", "savory", "sweet", "sticky",
    "loaded", "stuffed", "baked", "pan", "fried", "grilled", "roasted",
    "slow", "cooked", "pulled", "smashed", "toasted", "one", "pot", "skillet",
    "sheet", "pan", "one-pot",
}


def _title_tokens(title: str) -> set[str]:
    tokens = re.findall(r"[a-z]+", title.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def _title_similarity(a: str, b: str) -> float:
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Cache check
# ---------------------------------------------------------------------------

async def _check_cache_bulk(
    suggestion_names: list[str],
    db: AsyncSession,
    threshold: float = 0.55,
) -> dict[str, dict]:
    """
    Load the entire recipe cache once and match all suggestion names in-memory.
    Returns a dict mapping suggestion_name → recipe_dict for cache hits.
    This avoids concurrent DB access from parallel resolvers.
    """
    result = await db.execute(select(RecipeCache))
    rows = result.scalars().all()
    hits: dict[str, dict] = {}
    for name in suggestion_names:
        best, best_score = None, 0.0
        for row in rows:
            score = _title_similarity(name, row.title)
            if score > best_score:
                best_score = score
                best = row
        if best and best_score >= threshold:
            logger.debug("Cache hit for '%s' → '%s' (score=%.2f)", name, best.title, best_score)
            hits[name] = _cache_row_to_dict(best)
    return hits


def _cache_row_to_dict(row: RecipeCache) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "image": row.image or "",
        "prep_time": row.prep_time or 0,
        "cook_time": row.cook_time or 0,
        "total_time": row.total_time or 0,
        "difficulty": row.difficulty or "medium",
        "servings": row.servings or 4,
        "cuisine": row.cuisine or "",
        "meal_type": row.meal_type or [],
        "occasions": row.occasions or [],
        "rating": row.rating or 4.0,
        "source_url": row.source_url or "",
        "cooking_equipment": row.cooking_equipment or [],
        "ingredients": row.ingredients or [],
        "instructions": row.instructions or [],
        "score": 0.0,
        "source": "cache",
    }


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------

def _ddg_text_sync(query: str, max_results: int = 8) -> list[dict]:
    """Run synchronous DuckDuckGo search. Called via executor."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def _ddg_search(query: str, recipe_name: str = "", require_target_site: bool = True) -> Optional[str]:
    """DuckDuckGo search with retry + exponential backoff."""
    loop = asyncio.get_event_loop()
    max_retries = 3
    for attempt in range(max_retries):
        async with _SEARCH_SEM:
            try:
                results = await asyncio.wait_for(
                    loop.run_in_executor(_THREAD_POOL, _ddg_text_sync, query, 8),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                logger.warning("DDG search timed out for query: %s (attempt %d)", query[:80], attempt + 1)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
            except Exception as exc:
                exc_msg = str(exc)
                # Rate-limited or empty — retry with backoff
                if "No results" in exc_msg or "rate" in exc_msg.lower():
                    if attempt < max_retries - 1:
                        delay = 2 ** attempt + 1
                        logger.info("DDG rate-limited for '%s' — retrying in %ds (attempt %d)", query[:60], delay, attempt + 1)
                        await asyncio.sleep(delay)
                        continue
                logger.warning("DDG search error: %s", exc)
                return None

        if require_target_site:
            # First pass: prefer results from known recipe sites
            for r in results:
                url = r.get("href") or r.get("url") or ""
                if any(site in url for site in _ALL_SITES):
                    return url
            # Second pass: accept any result that looks like a recipe URL
            for r in results:
                url = r.get("href") or r.get("url") or ""
                if url and _looks_like_recipe_url(url, recipe_name):
                    return url
        else:
            for r in results:
                url = r.get("href") or r.get("url") or ""
                if url and _looks_like_recipe_url(url, recipe_name):
                    return url
            # Last resort: return first result that has any URL
            for r in results:
                url = r.get("href") or r.get("url") or ""
                if url:
                    return url
        # If search got results but none matched, don't retry
        if results:
            return None
        # No results at all — retry
        if attempt < max_retries - 1:
            await asyncio.sleep(1)
    return None


# Known recipe/cooking domains (broader than _ALL_SITES for URL validation)
_RECIPE_URL_INDICATORS = {
    "recipe", "recipes", "cooking", "cook", "food", "kitchen", "eat",
    "bake", "baking", "chef", "meal", "dinner", "lunch", "breakfast",
    "pasta", "chicken", "beef", "soup", "salad", "curry", "stir",
    "roast", "grilled", "fried", "sauteed", "braised",
}

# Domains that are definitely NOT recipe pages
_NON_RECIPE_DOMAINS = {
    "youtube.com", "amazon.com", "wikipedia.org", "pinterest.com",
    "facebook.com", "instagram.com", "twitter.com", "tiktok.com",
    "reddit.com", "quora.com", "yelp.com", "tripadvisor.com",
    "ebay.com", "walmart.com", "target.com", "etsy.com",
    "nytimes.com", "washingtonpost.com",  # paywalled
    "medium.com", "substack.com",
}


def _looks_like_recipe_url(url: str, recipe_name: str = "") -> bool:
    """
    Heuristic: does this URL look like it leads to a recipe page?
    Much more permissive than before — recipe-scrapers will validate the
    actual content, so we just need to avoid obvious non-recipe pages.
    """
    lower = url.lower()
    # Reject obviously non-recipe domains
    if any(domain in lower for domain in _NON_RECIPE_DOMAINS):
        return False
    # Accept if it's a known recipe site
    if any(site in lower for site in _ALL_SITES):
        return True
    # Accept if the URL path contains recipe-related words
    if any(indicator in lower for indicator in _RECIPE_URL_INDICATORS):
        return True
    # Accept if the URL path contains keywords from the recipe name
    # (e.g., "gochujang-pasta" in the URL for recipe "Gochujang Pasta")
    if recipe_name:
        name_tokens = set(re.findall(r"[a-z]+", recipe_name.lower()))
        name_tokens -= {"the", "a", "an", "and", "or", "with", "of", "in", "on"}
        # If at least 1 meaningful name word appears in the URL path, accept it
        if name_tokens and any(tok in lower for tok in name_tokens if len(tok) > 3):
            return True
    # Default: accept if it looks like a blog/food site (not a known bad domain)
    # Most food blogs are personal sites — we rely on recipe-scrapers to validate
    return True  # Permissive — let the scraper decide


async def _serpapi_search(query: str) -> Optional[str]:
    params = {"q": query, "api_key": SERPAPI_KEY, "num": 8, "engine": "google"}
    async with httpx.AsyncClient(timeout=WEB_RECIPE_TIMEOUT) as client:
        resp = await client.get("https://serpapi.com/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    # Prefer results from known recipe sites
    for result in data.get("organic_results", []):
        url = result.get("link", "")
        if any(site in url for site in _ALL_SITES):
            return url
    # Accept any recipe-looking result
    for result in data.get("organic_results", []):
        url = result.get("link", "")
        if url and _looks_like_recipe_url(url):
            return url
    results = data.get("organic_results", [])
    return results[0]["link"] if results else None


async def _search_recipe_urls(recipe_name: str, max_urls: int = 3) -> list[str]:
    """
    Multi-stage search — returns up to max_urls candidate URLs.
    Broad-first strategy for best relevance on niche/fusion dishes.
    """
    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str):
        if url and url not in seen and len(urls) < max_urls:
            seen.add(url)
            urls.append(url)

    broad_query = f"{recipe_name} recipe"

    # SerpAPI (if configured)
    if SERPAPI_KEY:
        try:
            url = await _serpapi_search(broad_query)
            _add(url)
        except Exception as exc:
            logger.warning("SerpAPI failed for '%s': %s", recipe_name, exc)

    # Stage 1: BROAD DDG query — returns multiple results
    loop = asyncio.get_event_loop()
    async with _SEARCH_SEM:
        try:
            results = await asyncio.wait_for(
                loop.run_in_executor(_THREAD_POOL, _ddg_text_sync, broad_query, 8),
                timeout=20.0,
            )
        except Exception:
            results = []

    # Prefer known sites, then recipe-looking URLs
    for r in (results or []):
        u = r.get("href") or r.get("url") or ""
        if u and any(site in u for site in _ALL_SITES):
            _add(u)
    for r in (results or []):
        u = r.get("href") or r.get("url") or ""
        if u and _looks_like_recipe_url(u, recipe_name):
            _add(u)

    if len(urls) >= max_urls:
        return urls

    # Stage 2: site-filtered fallback
    sites = _get_rotated_sites()
    site_filter = " OR ".join(f"site:{s}" for s in sites)
    targeted_query = f"{recipe_name} recipe {site_filter}"
    url = await _ddg_search(targeted_query, recipe_name=recipe_name, require_target_site=True)
    _add(url)

    return urls


async def _search_recipe_url(recipe_name: str) -> Optional[str]:
    """Convenience: return the single best URL (backwards compat)."""
    urls = await _search_recipe_urls(recipe_name, max_urls=1)
    return urls[0] if urls else None


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def _safe(fn, default):
    try:
        v = fn()
        return v if v is not None else default
    except Exception:
        return default


async def _scrape_recipe(url: str, suggestion: dict) -> Optional[dict]:
    """Fetch URL → recipe-scrapers → internal recipe dict."""
    async with _SCRAPE_SEM:
        try:
            async with httpx.AsyncClient(
                timeout=WEB_RECIPE_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            logger.warning("HTTP fetch failed for %s: %s", url, exc)
            return None

    try:
        scraper = scrape_html(html, org_url=url, wild_mode=True)
    except Exception as exc:
        logger.warning("recipe-scrapers parse failed for %s: %s", url, exc)
        return None

    try:
        title = _safe(scraper.title, "") or suggestion.get("name", "")
        raw_ingredients = _safe(scraper.ingredients, []) or []
        raw_instructions = _safe(scraper.instructions, "") or ""

        # Validate: reject if scraped title doesn't adequately overlap with the suggestion.
        # Threshold 0.3: allows 'Creamy Gochujang Pasta' → 'Gochujang Pasta' (sim ≈ 0.5 ✓)
        # but rejects 'Gochujang Pasta' → 'Gochujang Chickpeas' (sim ≈ 0.33 ✗) so the
        # caller retries with the next candidate URL.
        suggestion_name = suggestion.get("name", "")
        sim = _title_similarity(suggestion_name, title)
        if sim < 0.3 and suggestion_name:
            logger.warning(
                "Title mismatch: suggestion='%s' scraped='%s' (sim=%.2f) — skipping %s",
                suggestion_name, title, sim, url,
            )
            return None

        description = _safe(scraper.description, "") or ""
        if not description and raw_instructions:
            first = re.split(r'\.\s+', str(raw_instructions))[0].strip()
            if len(first) > 20:
                description = first + "."
        description = _clean_description(description, title)

        def _safe_int(fn, default):
            try:
                v = fn()
                return int(v) if v else default
            except Exception:
                return default

        # Trust scraped times — they come from the actual recipe author.
        # Only fall back to LLM estimate when the scraper returns nothing.
        raw_prep = _safe_int(scraper.prep_time, 0)
        raw_cook = _safe_int(scraper.cook_time, 0)
        raw_total = _safe_int(scraper.total_time, 0)

        if raw_total > 0:
            total_time = raw_total
            prep_time = raw_prep if raw_prep > 0 else max(0, total_time - raw_cook) if raw_cook > 0 else 0
            cook_time = raw_cook if raw_cook > 0 else max(0, total_time - raw_prep) if raw_prep > 0 else total_time
        elif raw_prep > 0 or raw_cook > 0:
            prep_time = raw_prep
            cook_time = raw_cook
            total_time = raw_prep + raw_cook
        else:
            # Scraper returned no time data at all — use LLM estimate as last resort
            llm_time = suggestion.get("estimated_time", 30)
            total_time = llm_time
            prep_time = 0
            cook_time = 0

        servings_raw = _safe(scraper.yields, "4 servings")
        servings_match = re.search(r"(\d+)", str(servings_raw))
        servings = int(servings_match.group(1)) if servings_match else 4

        image = _safe(scraper.image, "") or ""
        if image and not image.startswith("http"):
            image = ""

        cuisine = suggestion.get("cuisine", "")
        scraped_cuisine = _safe(scraper.cuisine, "") or ""
        if scraped_cuisine and not cuisine:
            cuisine = scraped_cuisine

        rating = 4.0
        raw_rating = _safe(scraper.ratings, None)
        if raw_rating is not None:
            try:
                r = float(raw_rating)
                if 1.0 <= r <= 5.0:
                    rating = round(r, 1)
            except (TypeError, ValueError):
                pass

        ingredients = [_parse_ingredient(ing) for ing in raw_ingredients if ing.strip()]
        instructions = _split_instructions(raw_instructions)

        if not ingredients and not instructions:
            logger.warning("Empty recipe from %s — skipping", url)
            return None

        recipe = {
            "id": _recipe_id_from_url(url),
            "title": title,
            "description": description,
            "image": image,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "difficulty": _difficulty_from_time(total_time),
            "servings": servings,
            "cuisine": cuisine,
            "meal_type": [],
            "occasions": [],
            "rating": rating,
            "source_url": url,
            "cooking_equipment": [],
            "ingredients": ingredients,
            "instructions": instructions,
            "score": 0.0,
            "source": "web",
        }

        logger.info(
            "Scraped '%s' | %s | image=%s | %d ingredients | %d steps | "
            "prep=%dmin cook=%dmin total=%dmin | cuisine=%s | rating=%.1f",
            title,
            url,
            "yes" if image else "none",
            len(ingredients),
            len(instructions),
            prep_time,
            cook_time,
            total_time,
            cuisine or "unknown",
            rating,
        )
        if ingredients:
            preview = ", ".join(
                f"{i['quantity']} {i['unit']} {i['name']}" for i in ingredients[:4]
            )
            logger.info(
                "  Ingredients: %s%s",
                preview,
                f" (+{len(ingredients) - 4} more)" if len(ingredients) > 4 else "",
            )

        return recipe

    except Exception as exc:
        logger.warning("Failed to extract fields from %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Per-suggestion resolver (used by asyncio.gather)
# ---------------------------------------------------------------------------

async def _resolve_suggestion(
    suggestion: dict,
    ctx: SessionContextRequest,
    cache_hits: dict[str, dict],
    seen_ids: set[str],
    seen_lock: asyncio.Lock,
    stagger_delay: float = 0.0,
    exclude_ids: set[str] | None = None,
) -> Optional[tuple[str, dict]]:
    """
    Resolve one LLM suggestion to a recipe dict.
    Uses pre-loaded cache_hits (no DB session needed — safe for concurrent use).
    Returns ("cache"|"web", recipe_dict) or None on failure.

    If ``exclude_ids`` is provided, cache hits whose ID is in the set are
    skipped (forces a web search fallback) so background fetches don't
    re-resolve recipes that are already in the session pool.
    """
    name = suggestion.get("name", "")
    if not name:
        return None

    # Stagger web searches to avoid DDG rate-limiting bursts
    if stagger_delay > 0:
        await asyncio.sleep(stagger_delay)

    # Step 1: check pre-loaded cache
    cached = cache_hits.get(name)
    if cached:
        # Skip cache hit if it's already known to the caller (e.g. already
        # in the session pool) — fall through to web search instead.
        if exclude_ids and cached["id"] in exclude_ids:
            logger.debug("Cache hit for '%s' already in pool (id=%s) — trying web instead", name, cached["id"][:8])
        else:
            async with seen_lock:
                if cached["id"] in seen_ids:
                    logger.debug("Duplicate cache hit for '%s' — skipping", name)
                    return None
                seen_ids.add(cached["id"])
            cached["meal_type"] = [ctx.meal_type]
            # Trust cached times from the original scrape — do NOT override with LLM estimate
            return ("cache", cached)

    # Step 2: web search + scrape (try multiple URLs on failure)
    urls = await _search_recipe_urls(name, max_urls=3)
    if not urls:
        logger.warning("No URL found for '%s'", name)
        return None

    for url in urls:
        recipe_id = _recipe_id_from_url(url)
        async with seen_lock:
            if recipe_id in seen_ids:
                logger.debug("URL already used (url=%s) — trying next for '%s'", url, name)
                continue
            seen_ids.add(recipe_id)

        recipe = await _scrape_recipe(url, suggestion)
        if recipe:
            recipe["meal_type"] = [ctx.meal_type]
            return ("web", recipe)

        # Scrape failed — free up the ID slot and try next URL
        async with seen_lock:
            seen_ids.discard(recipe_id)
        logger.info("Scrape failed for '%s' (%s) — trying next URL", name, url)

    logger.warning("All %d URLs failed for '%s'", len(urls), name)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_recipes_batch(
    suggestions: list[dict],
    ctx: SessionContextRequest,
    db: AsyncSession,
    progress_cb=None,
    exclude_ids: set[str] | None = None,
) -> list[dict]:
    """
    Stage 3 entry point. Resolves all LLM suggestions concurrently.

    Cache is loaded once upfront (single DB query) to avoid concurrent session
    access. Web search + scrape tasks run in parallel (bounded by _SEARCH_SEM /
    _SCRAPE_SEM) and never touch the DB session.

    progress_cb(done: int, total: int) is called after each suggestion resolves
    so the caller can track real-time fetch progress.

    If ``exclude_ids`` is provided, cache hits matching those IDs are skipped
    (the resolver falls through to web search). This prevents background
    fetches from re-resolving recipes already in the session pool.
    """
    seen_ids: set[str] = set()
    seen_lock = asyncio.Lock()

    logger.info("Stage 3: resolving %d suggestions concurrently", len(suggestions))

    # Single bulk cache load — avoids concurrent DB access from parallel tasks
    suggestion_names = [s.get("name", "") for s in suggestions if s.get("name")]
    cache_hits = await _check_cache_bulk(suggestion_names, db)
    logger.info("Stage 3: %d cache hits from %d suggestions", len(cache_hits), len(suggestion_names))

    _resolved_count = [0]
    _total = len(suggestions)

    async def _with_progress(coro):
        result = await coro
        _resolved_count[0] += 1
        if progress_cb:
            try:
                progress_cb(_resolved_count[0], _total)
            except Exception:
                pass
        return result

    tasks = [
        _with_progress(_resolve_suggestion(s, ctx, cache_hits, seen_ids, seen_lock,
                                           stagger_delay=i * 0.08,
                                           exclude_ids=exclude_ids))
        for i, s in enumerate(suggestions)
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[dict] = []
    cache_hits = web_hits = skipped = 0

    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("Suggestion resolver raised: %s", outcome)
            skipped += 1
        elif outcome is None:
            skipped += 1
        else:
            source, recipe = outcome
            results.append(recipe)
            if source == "cache":
                cache_hits += 1
            else:
                web_hits += 1

    logger.info(
        "Stage 3 complete: %d recipes resolved (%d cache, %d web, %d skipped/failed)",
        len(results), cache_hits, web_hits, skipped,
    )
    return results
