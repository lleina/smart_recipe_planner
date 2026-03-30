# Feature Reference — Smart Recipe Planner

> This document is the authoritative reference for every user-facing and
> developer-facing feature in the Smart Recipe Planner. Keep it updated when
> features are added, changed, or removed.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication & Onboarding](#2-authentication--onboarding)
3. [Ingredient Recognition via Camera](#3-ingredient-recognition-via-camera)
4. [Session Setup](#4-session-setup)
5. [Recipe Pipeline (Ideation → Fetch → Rank)](#5-recipe-pipeline-ideation--fetch--rank)
6. [Recipe Discovery Screen](#6-recipe-discovery-screen)
7. [Recipe Detail View](#7-recipe-detail-view)
8. [Saved Recipes](#8-saved-recipes)
9. [Cooking History](#9-cooking-history)
10. [User Profile & Preferences](#10-user-profile--preferences)
11. [Background Prefetching & Infinite Re-Ideation](#11-background-prefetching--infinite-re-ideation)
12. [Behavioral Event Tracking](#12-behavioral-event-tracking)
13. [API Reference Summary](#13-api-reference-summary)
14. [Configuration & Environment Variables](#14-configuration--environment-variables)
15. [Developer Tooling](#15-developer-tooling)

---

## 1. Overview

Smart Recipe Planner eliminates cooking decision fatigue. Given what is in your
fridge, how much time you have, and your dietary preferences, the app delivers
a curated, ranked list of real, web-scraped recipes — no made-up dishes, no
hallucinated ingredients.

**Core value loop:**
```
Take photo of ingredients → Set session context → Get ranked recipe list →
Browse → Save favourites → Mark as cooked → History informs future sessions
```

**Technology:**
- Mobile app: Expo (React Native) — iOS and Android
- Backend API: Python 3.12+ / FastAPI
- AI models: Qwen3 4B (text ideation + re-ranking) and Qwen3-VL 4B (vision) via Ollama
- Database: SQLite (default) or PostgreSQL (production)

---

## 2. Authentication & Onboarding

### 2.1 Registration and Login

| Aspect | Detail |
|--------|--------|
| Method | Email + password (bcrypt-hashed, minimum 6 characters) |
| Tokens | JWT access token (1-day TTL) + refresh token (30-day TTL) |
| Storage | Tokens stored in device `expo-secure-store` (hardware-backed on iOS) |
| Auto-refresh | Transparent: any 401 response triggers a silent token refresh before retry |
| Session persistence | App restores the authenticated session on cold start |

### 2.2 Offline-First Onboarding

New users complete dietary preferences setup **locally** before a backend
account is created. The backend registration is deferred until the first action
that requires server state (recipe recommendation, saving a recipe, etc.).

This means users can explore the onboarding flow without a network connection.

**Onboarding steps:**
1. Welcome / sign-in prompt
2. Cuisine preferences (multi-select)
3. Dietary restrictions (multi-select: vegetarian, vegan, gluten-free, dairy-free, etc.)
4. Health goal (balanced / high-protein / low-carb / weight-loss)
5. Cooking equipment available (oven, air fryer, instant pot, etc.)
6. Time preference (quick / moderate / weekend-cook)

---

## 3. Ingredient Recognition via Camera

### 3.1 Feature Description

Users can photograph their refrigerator, pantry, or individual ingredients. The
app sends the image to a vision-language model (VLM) which returns a structured
list of identified ingredients.

### 3.2 How It Works

1. User taps the camera icon in the Session Setup screen.
2. The app opens the device image picker (camera or gallery).
3. The image is compressed to ≤ 1 MB before upload (preserving aspect ratio).
4. The compressed image is POSTed to `POST /api/vlm` as a multipart upload.
5. The backend passes the image to Qwen3-VL 4B via Ollama.
6. The model returns a JSON list of detected ingredients.
7. Each ingredient is annotated with:
   - **name**: plain culinary name (brand names stripped)
   - **confidence**: 0.0–1.0 detection confidence
   - **category**: `perishable` / `semi-perishable` / `shelf-stable` / `frozen`
   - **urgency**: days until spoilage (perishables only; `null` for shelf-stable)
   - **estimated_quantity**: approximate amount detected
   - **unit**: `pieces` / `grams` / `ml` / etc.

### 3.3 Perishable Ingredient Prioritization

Ingredients with `urgency <= 3` (expiring within 3 days) receive a **+10 point
urgency boost** in the recipe ranking score. This nudges the system to suggest
recipes that use soon-to-expire ingredients, reducing food waste.

### 3.4 Constraints

- Maximum image upload size: **5 MB** (validated on both client and server)
- Supported formats: JPEG, PNG, WebP
- VLM timeout: configurable via `VLM_TIMEOUT_SECONDS` (default: 120 s)
- If the VLM is unavailable, users can still enter ingredients manually

---

## 4. Session Setup

Before requesting recipe recommendations, users configure a **session context**:

| Field | Description | Default |
|-------|-------------|---------|
| Meal type | breakfast / lunch / dinner / snack / dessert | dinner |
| Available time | How many total minutes the user can spend cooking | 45 min |
| Serving count | Number of people to cook for | 2 |
| Occasion | (Optional) weeknight / date-night / meal-prep / party | none |
| Available ingredients | List from VLM scan or manual entry | — |

The session context is stored in `SessionContext` (React) and persisted to the
backend `session_pool` table along with every recipe recommendation. This
enables re-ideation (see §11) using the same context later in the session.

---

## 5. Recipe Pipeline (Ideation → Fetch → Rank)

This is the core AI pipeline. It runs when the user taps **"Find Recipes"** and
produces a ranked list of real, web-scraped recipe cards.

### 5.1 Stage 1 — Context Assembly

The backend merges:
- Session context (meal type, time, ingredients, occasion)
- User preferences (dietary restrictions, cuisine affinities, equipment, health goal)
- Cooking history (last 10 cooked recipe titles — passed to LLM to avoid repetition)

### 5.2 Stage 2 — LLM Ideation

The text model (Qwen3 4B) generates **~40 recipe name suggestions** in JSON
format. The prompt includes:

- Available ingredients (with brand names stripped by a regex normalizer)
- Perishable ingredients called out explicitly to encourage their use
- Time budget and meal type
- Dietary restrictions as hard constraints
- Cuisine preferences as soft preferences
- Previous recipe titles as a "do not repeat" list

The model is instructed to produce varied suggestions (different cuisines,
techniques, and proteins) to maximize the chance of something appealing.

### 5.3 Stage 3a — Fast Fetch (synchronous)

The **first 15** suggestions are resolved immediately before the API response
is sent. For each suggestion:

1. The backend queries `recipe_cache` for an existing match (cache-first).
2. On a cache miss, DuckDuckGo is queried to find a matching recipe URL.
3. The URL is scraped using `recipe-scrapers` to extract structured data
   (title, ingredients, instructions, time, servings, cuisine, image).

Up to 5 concurrent searches and 10 concurrent scrapes run in parallel
(semaphore-controlled).

**Supported recipe sources**: AllRecipes, Food Network, BBC Good Food,
Serious Eats, NYT Cooking, Epicurious, and 35+ other major cooking sites via
the `recipe-scrapers` library. Optionally SerpAPI (paid) for higher search
reliability.

### 5.4 Stage 3b — Background Fetch (async)

The **remaining 25** suggestions are fetched concurrently in a background task
after the initial API response is sent. Results are appended to the session
pool in the database as they complete. The frontend polls for new recipes
automatically.

### 5.5 Stage 4 — Ranking

Recipes are ranked by one of three configurable modes:

#### Mode: `rules_only` (fast, deterministic)

Scores each recipe on a 100-point scale:

| Component | Max Points | Logic |
|-----------|-----------|-------|
| Time fit | 25 | Full score if within budget; -1.5 pts/min over; hard filter at +15 min over |
| Ingredient overlap | 40 | Fuzzy token match of recipe ingredients against user's available ingredients; pantry staples (salt, pepper, oil, vinegar, water) auto-counted |
| Key ingredient gap | -12 each (max -36) | Penalty for each "key" ingredient (protein, main component) the user is missing |
| Urgency boost | 10 | Bonus if any perishable ingredient (urgency ≤ 3 days) is used |
| Cuisine affinity | 15 | Bonus if recipe cuisine matches user preference |
| Equipment match | 10 | Bonus if recipe's required equipment matches user's available equipment |
| Recipe rating | 5 | Proportional to scraped star rating |

#### Mode: `llm_only` (slowest, highest potential quality)

All candidate recipes are passed directly to the LLM for ranking. The model
ranks by overall tastiness, appeal, variety, and novelty relative to the
session context.

#### Mode: `hybrid` (default)

1. Rule scorer ranks all candidates and selects the **top 15**.
2. Those 15 are passed to the LLM re-ranker.
3. Final ranking from the LLM is used as the served order.

The ranking mode can be set globally via `RANKING_MODE` environment variable,
or overridden per-request by the frontend via `ranking_mode` in the API body
(useful for A/B testing).

### 5.6 Stage 5 — Session Pool Persistence

The ranked recipe list is stored in the `session_pool` table with:
- Slot statuses: `unshown` / `shown` / `saved`
- Show timestamps for analytics
- Rank positions for future re-ideation

The first 5 recipes (one page) are marked `shown` and returned in the API
response. The rest remain `unshown` until the user pages forward.

---

## 6. Recipe Discovery Screen

### 6.1 Page-Based Navigation

The Discover screen shows **5 recipes per page** with Prev / Next navigation.
Pages are pre-fetched in the background (up to 8 pages ahead) so forward
navigation is usually instant.

| Control | Behaviour |
|---------|-----------|
| Next | Advances to the next page; triggers prefetch if needed |
| Prev | Navigates back instantly (recipes already in memory) |
| Haptic feedback | Light impact on every page turn |

### 6.2 Decision Fatigue Prompt

After **7 page turns** in a single session, the app shows a gentle prompt
suggesting the user refine their search or try a different session setup. This
is configurable via the `FATIGUE_THRESHOLD` constant in `discover.js`.

### 6.3 Recipe Cards

Each card displays:
- Recipe title and thumbnail image
- Total time (prep + cook)
- Difficulty badge (easy / medium / hard)
- Cuisine tag
- Ingredient match percentage (e.g. "You have 8 of 10 ingredients")
- Save button (bookmark icon; toggled per-recipe)
- Missing key ingredients highlighted

### 6.4 Substitution Pre-Fetching

As each recipe card is rendered, the app pre-fetches substitution suggestions
for missing ingredients in the background. When the user opens recipe detail,
substitution suggestions are available immediately (zero LLM wait).

---

## 7. Recipe Detail View

Accessed by tapping any recipe card. Displays:

| Section | Content |
|---------|---------|
| Header | Full-size image, title, time, servings, difficulty, cuisine, source attribution |
| Ingredients | Full list with matched/missing indicators per ingredient |
| Substitutions | AI-generated swap suggestions for ingredients the user doesn't have |
| Instructions | Numbered step-by-step cooking instructions |
| Save button | Adds/removes from saved collection |
| Mark as Cooked | Logs the recipe to cooking history |
| Source link | Links to the original recipe page |

### 7.1 Ingredient Substitution Feature

For each missing ingredient, the backend generates substitution suggestions
using the LLM. A substitution entry includes:
- The missing ingredient name
- A list of viable substitutes from the user's available ingredients (preferred)
  or generic alternatives
- Brief notes on how the substitution affects the dish

---

## 8. Saved Recipes

Users can save any recipe from the Discovery screen or Recipe Detail view.

| Behaviour | Detail |
|-----------|--------|
| Storage | Saved in `saved_recipes` table; linked to `recipe_cache` entry |
| Offline access | Saved recipe metadata displayed even if source URL is unavailable |
| Unsave | One-tap from the Saved screen or from Recipe Detail |
| Sort order | Most recently saved first |

The saved recipe list is loaded into `SavedRecipesContext` on app start and
kept in sync with optimistic UI updates (UI updates immediately; API call fires
in background).

---

## 9. Cooking History

When a user marks a recipe as cooked, a `CookHistory` entry is created:

| Field | Description |
|-------|-------------|
| Recipe | Links to `recipe_cache` entry |
| Cooked at | UTC timestamp |
| Meal type | The meal type from the session when the recipe was cooked |
| Serving count | How many people it was cooked for |
| Session ID | The session pool that surfaced the recipe |

**History informs future recommendations**: the last 10 cooked recipe titles
are passed to the LLM ideation stage as a "do not repeat" signal.

The History screen shows the 50 most recent entries with recipe thumbnail,
title, cook date, and meal type.

---

## 10. User Profile & Preferences

Users can update all preferences set during onboarding at any time from the
Profile tab:

- Cuisine preferences
- Dietary restrictions
- Health goal
- Time preference
- Cooking equipment
- Perishable optimization toggle (on/off)

Changes take effect on the next recipe session. Preferences are persisted to
the backend `user_preferences` table and are independent of session context.

---

## 11. Background Prefetching & Infinite Re-Ideation

### 11.1 Eager Prefetch

After delivering the first page of recipes, the frontend immediately begins
fetching subsequent pages from the backend pool in the background. The
`RecipeContext` prefetcher:

- Maintains a buffer of up to **8 pages ahead** of the current page
- Uses exponential backoff (1.5 s → 5 s) when the backend pool is still
  populating
- Retries up to **20 times** before giving up on an empty page
- Never shows a duplicate recipe (deduplication via `shownIdsRef` Set)

### 11.2 Unlimited Re-Ideation

When the session pool runs low (fewer than **15 unshown recipes** remain after
serving a page), the backend **automatically triggers a new LLM ideation
round** in the background. The threshold is set to 3× the page size so the
user always has at least two full pages buffered before the new fetch
completes. The new round:

1. Queries the LLM for 40 fresh recipe suggestions
2. Excludes all previously seen recipe titles via the history list
3. Fetches, scrapes, and ranks the new suggestions
4. Appends new recipes to the session pool

This cycle repeats up to **20 times** per session (`MAX_REFETCH_ROUNDS`),
giving users a theoretically unlimited supply of novel, relevant recipes within
a single session.

---

## 12. Behavioral Event Tracking

The app logs lightweight events for analytics and future personalization:

| Event type | Fired when |
|-----------|-----------|
| `session_started` | User begins a new recipe session |
| `recipe_shown` | A recipe card is displayed to the user |
| `recipe_saved` | User saves a recipe |
| `recipe_unsaved` | User removes a saved recipe |
| `recipe_cooked` | User marks a recipe as cooked |
| `next_page` | User navigates to the next page of recipes |
| `rerank_triggered` | User triggers a re-rank based on a liked recipe |

Events are sent to `POST /api/events` (fire-and-forget; errors do not affect
UX). Each event records the user ID, session ID, recipe ID (if applicable),
event type, and a flexible `metadata` JSON object.

---

## 13. API Reference Summary

All endpoints require a Bearer token except `/api/auth/*`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check — returns DB, VLM, and LLM status |
| `POST` | `/api/auth/register` | Create a new user account |
| `POST` | `/api/auth/login` | Authenticate and receive tokens |
| `POST` | `/api/auth/refresh` | Exchange a refresh token for a new access token |
| `GET` | `/api/user/preferences` | Retrieve the authenticated user's preferences |
| `PUT` | `/api/user/preferences` | Update the authenticated user's preferences |
| `POST` | `/api/vlm` | Upload an image; returns identified ingredient list |
| `POST` | `/api/recommend` | Run the full recipe pipeline; returns first page |
| `GET` | `/api/recommend/next` | Get the next page of recipes from an existing pool |
| `GET` | `/api/recommend/status` | Poll pipeline progress (step, label, detail) |
| `POST` | `/api/rerank` | Signal a preference (saves recipe signal to pool) |
| `GET` | `/api/saved` | List the user's saved recipes |
| `POST` | `/api/saved` | Save a recipe |
| `DELETE` | `/api/saved/{id}` | Remove a saved recipe |
| `GET` | `/api/history` | List the user's cooking history |
| `POST` | `/api/history` | Log a cooked recipe |
| `POST` | `/api/events` | Record a behavioral event |
| `GET` | `/api/recipe/{id}` | Get full recipe detail + substitution suggestions |

### Error Response Format

All errors use a consistent JSON shape (see `ErrorResponse` schema):

```json
{
  "error": {
    "code": "HTTP_404",
    "message": "Session pool not found",
    "retryable": false
  }
}
```

---

## 14. Configuration & Environment Variables

### 14.1 Backend (`backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data.db` | Database connection string |
| `JWT_SECRET` | *(required)* | Secret key for signing JWT tokens — use a long random string in production |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_DAYS` | `1` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifetime |
| `VLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint for the vision model |
| `VLM_MODEL` | `qwen3-vl:4b` | Vision model identifier |
| `VLM_TIMEOUT_SECONDS` | `120` | Maximum seconds to wait for a VLM response |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint for the text model |
| `LLM_MODEL` | `qwen3:4b` | Text model identifier |
| `LLM_TIMEOUT_SECONDS` | `90` | Maximum seconds to wait for an LLM response |
| `LLM_API_KEY` | `ollama` | API key (use `ollama` for local Ollama) |
| `RANKING_MODE` | `hybrid` | `hybrid` / `rules_only` / `llm_only` |
| `SERPAPI_KEY` | *(optional)* | SerpAPI key for enhanced web search reliability |
| `WEB_RECIPE_SITES` | *(see `.env.example`)* | Space-separated list of target recipe domains |

> Set `VLM_BASE_URL` or `LLM_BASE_URL` to an empty string to disable the
> respective AI call and use mock/fallback data — useful for frontend-only
> development without Ollama running.

### 14.2 Frontend (`frontend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPO_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend API base URL |

For WSL2 development, set this to your machine's IP address. Use
`backend/scripts/start_api_tunnel.sh` to automatically configure the tunnel.

---

## 15. Developer Tooling

### 15.1 Start Everything

```bash
./start_all.sh   # Starts Ollama, backend (uvicorn), and frontend (expo)
./stop_all.sh    # Graceful shutdown (optionally preserves Ollama)
```

### 15.2 Backend Scripts

| Script | Purpose |
|--------|---------|
| `backend/scripts/setup_ollama.sh` | One-time: installs Ollama and downloads both AI models (~6 GB) |
| `backend/scripts/start_models.sh` | Starts Ollama server and warms up models |
| `backend/scripts/start_api_tunnel.sh` | WSL2 tunnel: exposes backend to mobile device on LAN |
| `backend/scripts/seed_cache.py` | Pre-populate recipe cache with common recipes to speed up first runs |
| `backend/e2e_test.py` | End-to-end integration test: register → recommend → next → rerank |

### 15.3 Running Tests

```bash
# Frontend (Jest)
cd frontend && npm test

# Backend (pytest)
cd backend && source venv/bin/activate && pytest

# Backend E2E (requires running server)
cd backend && python e2e_test.py
```

### 15.4 Linting

```bash
# Python (run from backend/)
pylint app/ --fail-under=9.0
ruff check .
black --check .

# JavaScript (run from frontend/)
npx eslint .
npx prettier --check .
```

---

*Document owner: Engineering — last updated 2026-03-30.*
