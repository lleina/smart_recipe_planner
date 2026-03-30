# Coding Standards — Smart Recipe Planner

> These standards apply to every file in this repository: Python backend and
> JavaScript/React Native frontend. All code merged to `main` must pass these
> standards. When in doubt, optimize for **readability first**, then correctness,
> then performance.

---

## Table of Contents

1. [Core Philosophy](#1-core-philosophy)
2. [Documentation](#2-documentation)
3. [Naming Conventions](#3-naming-conventions)
4. [Function Design](#4-function-design)
5. [Python-Specific Standards](#5-python-specific-standards)
6. [JavaScript / React Native Standards](#6-javascript--react-native-standards)
7. [Error Handling](#7-error-handling)
8. [Constants and Configuration](#8-constants-and-configuration)
9. [Testing](#9-testing)
10. [Git and Commit Hygiene](#10-git-and-commit-hygiene)

---

## 1. Core Philosophy

**Write code for the next engineer, not the computer.**

- Every non-trivial decision must be explainable in a comment or docstring.
- Prefer explicit over implicit — name things what they are.
- A function should do one thing and do it well. If you need "and" to describe
  what a function does, it should be two functions.
- Flat is better than nested. Maximum nesting depth: **3 levels** for logic
  blocks (loops, conditionals, try/except). Refactor anything deeper into a
  named helper.
- Delete dead code. Comments like `# TODO: remove this` are not acceptable on
  merge; either fix it or open a tracked issue.

---

## 2. Documentation

Documentation is a first-class citizen — not an afterthought.

### 2.1 Every public symbol must have a docstring / JSDoc

**Python** — use multi-line docstrings for all public modules, classes,
functions, and methods. Use the following format:

```python
def score_recipe_by_time(recipe: dict, available_minutes: int) -> float:
    """
    Return a time-fit score (0–25) based on how well the recipe's total time
    fits within the user's available cooking time.

    A recipe that fits within the budget scores 25. Each minute over budget
    deducts 1.5 points, capped at 0. Recipes more than 15 minutes over budget
    are hard-filtered upstream and should never reach this function.

    Args:
        recipe: Fetched recipe dict containing ``total_time`` (int, minutes).
        available_minutes: User's stated cooking time budget in minutes.

    Returns:
        Score between 0.0 and 25.0 (inclusive).
    """
```

**JavaScript** — use JSDoc for all exported functions, hooks, and context
providers:

```js
/**
 * Formats a duration in minutes into a human-readable string.
 *
 * @param {number} totalMinutes - Total duration in minutes (must be >= 0).
 * @returns {string} Formatted string, e.g. "1 hr 15 min" or "30 min".
 */
export function formatDuration(totalMinutes) { ... }
```

### 2.2 Module-level docstrings

Every file must open with a module docstring (Python) or block comment (JS)
explaining:
1. **What** the module does.
2. **Why** it exists (what problem it solves, or what architectural role it plays).
3. Any non-obvious constraints or dependencies.

### 2.3 Inline comments

Use inline comments to explain **why**, not **what**. The code itself shows what
happens; the comment explains the intent behind the decision.

```python
# Good — explains the reasoning
# Deduct up to 3 key-ingredient penalties; beyond 3 the recipe is likely
# a completely different dish and will be hard-filtered anyway.
penalty = min(missing_key_count, 3) * KEY_INGREDIENT_PENALTY_PTS

# Bad — restates the code
penalty = missing_key_count * KEY_INGREDIENT_PENALTY_PTS  # multiply by penalty
```

### 2.4 TODO comments

Any `TODO` comment must include a reference to the owner or a tracking issue:

```python
# TODO(leina): Switch to SerpAPI when budget allows — see issue #42
```

Bare `TODO` or `FIXME` comments without context will be rejected in review.

---

## 3. Naming Conventions

### 3.1 General rules (both languages)

| Rule | Good | Bad |
|------|------|-----|
| Names must describe **what the thing is or does** | `available_ingredient_tokens` | `tokens`, `t`, `data` |
| Booleans start with `is`, `has`, `can`, or `should` | `is_buffering`, `has_next_page` | `buffering`, `next_page` |
| Collections are plural nouns | `recipe_entries`, `suggestion_titles` | `list`, `items`, `arr` |
| Functions that perform I/O use verbs | `fetch_recipe_from_cache`, `save_user_preferences` | `recipe`, `get` |
| Constants are SCREAMING_SNAKE_CASE | `MAX_REFETCH_ROUNDS`, `BATCH_SIZE` | `max`, `batchSize` |
| Avoid abbreviations except universally known ones | `html`, `url`, `id`, `db` | `usr`, `rec`, `cfg`, `mgr` |

### 3.2 Python naming

| Symbol | Convention | Example |
|--------|-----------|---------|
| Module | `snake_case` | `ranking_service.py` |
| Class | `PascalCase` | `RecipeCache`, `SessionPool` |
| Function / method | `snake_case` | `score_time_fit`, `build_prompt` |
| Private helper | `_snake_case` (single leading underscore) | `_extract_json_from_llm_response` |
| Module-level constant | `SCREAMING_SNAKE_CASE` | `PANTRY_STAPLES`, `BATCH_SIZE` |
| Type alias | `PascalCase` | `RecipeDict = dict[str, Any]` |

Private helpers (single underscore prefix) are acceptable for module-internal
functions that should never be imported by other modules. Do **not** use double
underscores (`__`) except for Python dunder methods.

### 3.3 JavaScript / React Native naming

| Symbol | Convention | Example |
|--------|-----------|---------|
| File | `camelCase.js` | `pipelineService.js` |
| React component file | `PascalCase.js` | `RecipeCard.js` |
| Variable / function | `camelCase` | `fetchNextRecipeBatch` |
| React component | `PascalCase` | `RecipeCard`, `DiscoverScreen` |
| React hook | `use` prefix + `PascalCase` | `useRecipeContext`, `useSession` |
| Context | `PascalCase` + `Context` suffix | `RecipeContext`, `AuthContext` |
| Module constant | `SCREAMING_SNAKE_CASE` | `PAGE_SIZE`, `PREFETCH_RETRY_DELAY_MS` |
| Event handler | `handle` prefix | `handleSaveRecipe`, `handleNextPage` |
| Boolean state / prop | `is` / `has` / `can` prefix | `isBuffering`, `hasPrevPage` |

### 3.4 Loop variables and short-lived locals

Use descriptive names even for short-lived variables in loops:

```python
# Good
for recipe_entry in pool_recipes:
    if recipe_entry["recipeId"] == target_id:
        ...

# Bad
for r in pool_recipes:
    if r["recipeId"] == target_id:
        ...
```

Single-letter variables (`i`, `j`, `k`) are only acceptable as numeric indices
in mathematical algorithms, not as object references.

---

## 4. Function Design

### 4.1 Single Responsibility

Each function does exactly one thing. If it requires more than one paragraph to
describe in a docstring, it should be split.

### 4.2 Maximum nesting depth: 3

Refactor nested logic into named helpers. Early returns and guard clauses
flatten nesting naturally:

```python
# Good — guard clause, flat body
async def append_recipe_to_pool(recipe: dict, pool: SessionPool, db: AsyncSession) -> bool:
    if recipe["id"] in existing_pool_ids:
        return False
    if recipe["total_time"] > MAX_RECIPE_TIME_MINUTES:
        return False

    await _persist_recipe_cache_entry(recipe, db)
    _add_recipe_to_pool_list(recipe, pool)
    return True

# Bad — deeply nested
async def append_recipe_to_pool(recipe, pool, db):
    if recipe["id"] not in existing_pool_ids:
        if recipe["total_time"] <= MAX_RECIPE_TIME_MINUTES:
            await _persist_recipe_cache_entry(recipe, db)
            _add_recipe_to_pool_list(recipe, pool)
            return True
    return False
```

### 4.3 Maximum function length: ~60 lines

If a function body approaches 60 lines, it almost certainly has more than one
responsibility. Extract named helpers.

### 4.4 Function parameters

- Prefer keyword arguments for functions with more than 3 parameters.
- Use type annotations in Python; JSDoc types in JavaScript.
- Never use mutable defaults in Python (`def foo(items=[])`).

### 4.5 Return types

Functions must have a single, consistent return type. A function that sometimes
returns `None` and sometimes a `dict` is a design smell — use `Optional[dict]`
and document when `None` is returned and why.

---

## 5. Python-Specific Standards

### 5.1 Type hints

All function signatures must include type hints. Use `from __future__ import
annotations` for forward references when needed.

```python
async def rank_recipes(
    recipes: list[dict],
    context: SessionContextRequest,
    dietary_restrictions: list[str],
    mode: str = "hybrid",
) -> list[dict]:
```

### 5.2 Imports

Group imports in this order (one blank line between each group):
1. Standard library (`import asyncio`, `import json`)
2. Third-party (`from fastapi import ...`, `from sqlalchemy import ...`)
3. Local application (`from app.models import ...`)

Avoid wildcard imports (`from module import *`).

### 5.3 Async / await

- All database calls and HTTP requests must be `async`.
- Never call `asyncio.run()` inside an already-running event loop.
- Background tasks (`asyncio.create_task`) must log on entry, success, and failure.

### 5.4 Exception handling

Catch specific exceptions, not bare `except Exception` unless you are a
top-level error boundary:

```python
# Good
try:
    result = await db.execute(query)
except SQLAlchemyError as exc:
    logger.error("Database query failed: %s", exc)
    raise

# Bad
try:
    result = await db.execute(query)
except:
    pass
```

### 5.5 Logging

- Use the module-level logger pattern: `logger = logging.getLogger("app.module_name")`.
- Use `%`-style formatting (not f-strings) in log calls — the string is only
  formatted when the log level is active.
- Log at the correct level: `DEBUG` for verbose trace, `INFO` for normal flow,
  `WARNING` for recoverable unexpected state, `ERROR` for failures.

### 5.6 Linting and formatting

All Python files must pass all three tools before merge:

| Tool | Purpose | Command |
|------|---------|---------|
| **Pylint** | Semantic analysis, unused variables, complexity, naming | `pylint app/` |
| **Ruff** | Fast linting + import sort (replaces flake8 / isort) | `ruff check .` |
| **Black** | Opinionated auto-formatter (line length 88) | `black --check .` |

Run order matters: fix **Black** first (formatting), then **Ruff** (import
order, style), then **Pylint** (semantic issues). A pre-commit hook runs all
three automatically.

**Pylint score requirement**: every module must score **≥ 9.0 / 10.0**. Scores
below this threshold will fail CI. To check a single file:

```bash
pylint app/services/ranking_service.py --fail-under=9.0
```

**Acceptable Pylint suppressions** (with justification comment required):

```python
# pylint: disable=too-many-arguments  # Pipeline orchestrator legitimately needs
                                       # all context fields; splitting would hide coupling.
```

Never suppress `invalid-name`, `missing-docstring`, or `broad-except` without
a very strong justification — these categories catch the most real bugs.

Configuration lives in `pyproject.toml` (Black/Ruff) and `.pylintrc` at the
backend root.

---

## 6. JavaScript / React Native Standards

### 6.1 React hooks

- Hooks must follow the [Rules of Hooks](https://react.dev/warnings/invalid-hook-call-warning).
- Use `useEffect` for side effects. **Never use `useMemo` to trigger side effects** — `useMemo` is for computing derived values only.
- Use `useCallback` for functions passed as props or dependencies.
- Ref values (`useRef`) must be named with a `Ref` suffix: `recipesRef`, `currentPageRef`.

### 6.2 Component structure

Each React component file follows this order:
1. Module docblock
2. Imports (external libs, then internal)
3. Module-level constants (non-reactive)
4. Component function
   a. Hooks (state, context, refs)
   b. Derived values (`useMemo`)
   c. Callbacks (`useCallback`)
   d. Effects (`useEffect`)
   e. Return (JSX)
5. Exported helpers or sub-components

### 6.3 Context providers

- Each context file exports exactly one `Provider` component and one
  `use<Name>` hook.
- The `use<Name>` hook must throw a clear error when consumed outside its
  Provider:
  ```js
  if (!context) throw new Error('useRecipeContext must be used inside RecipeProvider');
  ```

### 6.4 State management

- Keep state as local as possible. Lift to context only when shared across
  routes.
- Do not store derived values in state — compute them with `useMemo`.
- Avoid parallel `ref` mirrors of state (e.g., `recipes` + `recipesRef`) unless
  strictly necessary for async closure correctness; document why when used.

### 6.5 Error boundaries

All top-level screens must handle error state explicitly and show a
user-friendly message — never a raw JavaScript exception.

### 6.6 Linting and formatting

All JS files must pass:
- **ESLint** with the project config: `npx eslint .`
- **Prettier**: `npx prettier --check .`

---

## 7. Error Handling

### 7.1 Never swallow errors silently

```python
# Bad
except Exception:
    pass

# Good
except Exception as exc:
    logger.warning("Non-critical background task failed: %s", exc)
```

### 7.2 User-facing error messages

- Must be actionable: "No recipes found for your available ingredients — try
  adding a protein or reducing time constraints."
- Must not expose internal details: no stack traces, SQL errors, or raw
  exception messages.

### 7.3 API error codes

All API errors use the `ApiError` class with a machine-readable `code` field:
`ERR_TIMEOUT`, `HTTP_401`, `ERR_NETWORK`, etc. Frontend error handling branches
on `code`, not on message strings.

---

## 8. Constants and Configuration

- Never hard-code numeric literals in business logic. Extract them to named
  constants at the top of the module with a comment explaining the value.

```python
# Maximum number of re-ideation rounds per session to prevent runaway AI calls.
MAX_REFETCH_ROUNDS = 20

# Hard filter: reject recipes exceeding available time by more than this margin.
TIME_BUDGET_OVERFLOW_LIMIT_MINUTES = 15
```

- Environment-driven config lives in `backend/app/config.py` (Python) or
  `frontend/src/constants/config.js` (JS).
- Never commit real secrets. `.env` files are git-ignored; `.env.example`
  contains only placeholder values.

---

## 9. Testing

### 9.1 What to test

- Every public utility function must have unit tests.
- Every API route must have at least one integration test (success + failure path).
- Every React hook must have at least one unit test verifying its state transitions.

### 9.2 Test naming

Test names follow the pattern: `test_<function>_<scenario>_<expected_outcome>`:

```python
def test_score_time_fit_within_budget_returns_full_score():
    ...

def test_score_time_fit_over_budget_deducts_proportionally():
    ...
```

### 9.3 No implementation details in tests

Test behavior, not implementation. Assert on outputs and observable side
effects, not on internal variable names or call counts (unless testing a mock
boundary).

---

## 10. Git and Commit Hygiene

### 10.1 Branch naming

```
feature/<short-description>     # new features
fix/<short-description>         # bug fixes
refactor/<short-description>    # non-functional improvements
docs/<short-description>        # documentation only
```

### 10.2 Commit messages

Follow conventional commits:

```
feat: add urgency boost to recipe ranking score
fix: prevent duplicate recipes when background fetch overlaps initial fetch
refactor: extract _build_available_token_set into its own helper
docs: add module-level docstring to ranking_service.py
```

Subject line: imperative mood, ≤72 characters, no trailing period.

### 10.3 One logical change per commit

A commit should pass all tests on its own and represent one coherent change. If
you find yourself writing "and" in the commit message, split the commit.

### 10.4 Pull requests

Every PR must include:
1. A description of **what** changed and **why**.
2. A test plan (steps to manually verify or automated test output).
3. A link to the relevant issue or design doc.

---

*Document owner: Engineering — last updated 2026-03-30.*
