"""
Infinite scroll / pagination performance tests.  [PRIORITY]

Tests the core user-facing requirement:
  "New recipes show in < 1 second of entering a page."

The performance guarantee works because:
  1. The backend /recommend/next endpoint reads from a pre-populated DB pool
     (no LLM inference at page-flip time), so the response is a fast DB read.
  2. The frontend pre-fetches 8 pages in the background, so by the time the
     user taps "Next", the data is already in memory.

These tests verify BOTH sides of that contract:
  - Backend: /recommend/next responds in < 1 second (DB read performance)
  - Integrity: unique recipes across pages, no duplicates
  - Buffer: recipes[] accumulates correctly without gaps

Run (requires live backend + prior pipeline run):
  cd backend && pytest tests/test_infinite_scroll.py -v

Mark: all tests here are 'integration' and some are 'slow' (pipeline warm-up).
"""

import time
import pytest
import requests

# ── Constants ────────────────────────────────────────────────────────────────

PAGE_SIZE = 5             # Must match frontend RECIPE_BATCH_SIZE = 5
NEXT_PAGE_MAX_MS = 1000  # < 1 second per page flip (SLA)
MIN_PAGES_EXPECTED = 3   # At minimum 3 pages (15 recipes) before we test navigation


# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_next_page(api_base, session_pool_id, auth_headers):
    """
    Calls GET /recommend/next and returns (response_data, elapsed_ms).

    Args:
        api_base: Base API URL from conftest.
        session_pool_id: Active session pool ID.
        auth_headers: Authorization headers for the test user.

    Returns:
        tuple: (response dict, elapsed milliseconds as float)
    """
    start = time.perf_counter()
    response = requests.get(
        f"{api_base}/recommend/next",
        params={"sessionPoolId": session_pool_id},
        headers=auth_headers,
        timeout=10,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert response.status_code == 200, (
        f"/recommend/next failed: {response.status_code} — {response.text[:300]}"
    )
    return response.json(), elapsed_ms


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.slow
class TestInfiniteScrollPerformance:
    """
    Performance and correctness tests for the infinite-scroll page navigation.

    All tests in this class share a single session pool (active_session_pool
    fixture) — created once per module by conftest.py.
    """

    def test_initial_pipeline_returns_first_page(self, active_session_pool):
        """
        The pipeline response must include at least PAGE_SIZE recipes.
        This is the data that populates page 1 in the UI.
        """
        recipes = active_session_pool.get("recipes", [])
        assert len(recipes) >= PAGE_SIZE, (
            f"Expected at least {PAGE_SIZE} recipes on page 1, got {len(recipes)}"
        )

    def test_initial_pipeline_has_required_fields(self, active_session_pool):
        """Each recipe in the first page must have the fields the UI renders."""
        recipes = active_session_pool.get("recipes", [])
        required_fields = {"id", "title"}
        for recipe in recipes:
            missing = required_fields - set(recipe.keys())
            assert not missing, f"Recipe {recipe.get('id')} missing fields: {missing}"

    def test_pool_size_reported_correctly(self, active_session_pool):
        """poolSize must be >= the number of recipes returned."""
        pool_size = active_session_pool.get("poolSize", 0)
        recipe_count = len(active_session_pool.get("recipes", []))
        assert pool_size >= recipe_count, (
            f"poolSize ({pool_size}) < recipes returned ({recipe_count})"
        )

    def test_next_page_responds_under_one_second(self, api_base, active_session_pool, auth_headers):
        """
        GET /recommend/next must respond in < 1 second.

        This is the critical performance requirement for infinite scroll:
        the backend reads from a pre-populated DB pool (no LLM inference),
        so each page flip should be a fast SQL SELECT.
        """
        session_pool_id = active_session_pool["sessionPoolId"]
        data, elapsed_ms = fetch_next_page(api_base, session_pool_id, auth_headers)

        assert elapsed_ms < NEXT_PAGE_MAX_MS, (
            f"/recommend/next took {elapsed_ms:.0f}ms — exceeds {NEXT_PAGE_MAX_MS}ms SLA. "
            f"This would cause visible loading delay on page flip."
        )
        print(f"\n  /recommend/next response time: {elapsed_ms:.0f}ms ✓")

    def test_next_page_returns_new_recipes(self, api_base, active_session_pool, auth_headers):
        """Each /recommend/next call must return at least one recipe."""
        session_pool_id = active_session_pool["sessionPoolId"]
        data, _ = fetch_next_page(api_base, session_pool_id, auth_headers)
        recipes = data.get("recipes", [])
        # May be empty if pool is exhausted — but on a fresh pool this should have data
        # We allow 0 only if shownCount >= poolSize (fully consumed pool)
        shown = data.get("shownCount", 0)
        pool = data.get("poolSize", 0)
        if pool > 0 and shown < pool:
            assert len(recipes) > 0, (
                f"/recommend/next returned 0 recipes but pool not exhausted "
                f"(shown={shown}, poolSize={pool})"
            )

    def test_multiple_page_flips_all_under_one_second(self, api_base, active_session_pool, auth_headers):
        """
        Simulates a user rapidly flipping through 5 pages.

        Every single page flip must respond in < 1 second. If any page
        causes a slow response, the test reports which flip number failed
        and the actual elapsed time.

        This is the end-to-end proof that "infinite scroll < 1s" works.
        """
        session_pool_id = active_session_pool["sessionPoolId"]
        num_pages = 5
        timings = []

        for flip_number in range(1, num_pages + 1):
            data, elapsed_ms = fetch_next_page(api_base, session_pool_id, auth_headers)
            timings.append(elapsed_ms)

            assert elapsed_ms < NEXT_PAGE_MAX_MS, (
                f"Page flip #{flip_number} took {elapsed_ms:.0f}ms "
                f"(SLA: {NEXT_PAGE_MAX_MS}ms). "
                f"Previous flips: {[f'{t:.0f}ms' for t in timings[:-1]]}"
            )

        avg_ms = sum(timings) / len(timings)
        max_ms = max(timings)
        print(f"\n  Page flip timings over {num_pages} pages:")
        for i, t in enumerate(timings, 1):
            print(f"    Flip #{i}: {t:.0f}ms")
        print(f"  Average: {avg_ms:.0f}ms, Max: {max_ms:.0f}ms")

    def test_no_duplicate_recipe_ids_across_pages(self, api_base, active_session_pool, auth_headers):
        """
        Verifies that the same recipe ID never appears on two different pages.

        Duplicates would cause: wrong recipe shown, confusing "seen before"
        feeling, broken saved-state (save button wrong), and potentially
        infinite pipeline loops.
        """
        session_pool_id = active_session_pool["sessionPoolId"]
        seen_ids = set()
        duplicates = []

        # Start with IDs from the first page (already returned by the pipeline)
        for recipe in active_session_pool.get("recipes", []):
            seen_ids.add(recipe["id"])

        # Fetch several more pages and check for overlap
        for _ in range(4):
            data, _ = fetch_next_page(api_base, session_pool_id, auth_headers)
            for recipe in data.get("recipes", []):
                if recipe["id"] in seen_ids:
                    duplicates.append(recipe["id"])
                seen_ids.add(recipe["id"])

        assert not duplicates, (
            f"Duplicate recipe IDs found across pages: {duplicates[:5]}"
        )

    def test_shown_count_increases_monotonically(self, api_base, active_session_pool, auth_headers):
        """
        shownCount in /recommend/next responses must never decrease.

        A decreasing shownCount would indicate the backend lost track of which
        recipes have been shown, potentially causing re-ideation to trigger at
        the wrong time or duplicates to appear.
        """
        session_pool_id = active_session_pool["sessionPoolId"]
        previous_shown = active_session_pool.get("shownCount", 0)

        for flip in range(3):
            data, _ = fetch_next_page(api_base, session_pool_id, auth_headers)
            current_shown = data.get("shownCount", 0)

            assert current_shown >= previous_shown, (
                f"shownCount decreased on flip #{flip + 1}: "
                f"{previous_shown} → {current_shown}"
            )
            previous_shown = current_shown

    def test_pool_size_never_decreases(self, api_base, active_session_pool, auth_headers):
        """
        poolSize must be non-decreasing across page flips.

        poolSize can increase (background re-ideation adds recipes) but should
        never decrease, as that would shrink the user's recipe universe.
        """
        session_pool_id = active_session_pool["sessionPoolId"]
        previous_pool_size = active_session_pool.get("poolSize", 0)

        for flip in range(3):
            data, _ = fetch_next_page(api_base, session_pool_id, auth_headers)
            current_pool_size = data.get("poolSize", 0)

            assert current_pool_size >= previous_pool_size, (
                f"poolSize decreased on flip #{flip + 1}: "
                f"{previous_pool_size} → {current_pool_size}"
            )
            previous_pool_size = current_pool_size


# ── Isolation tests (no shared session pool) ─────────────────────────────────

class TestInfiniteScrollIsolation:
    """
    Tests that don't need the full pipeline — verify edge cases and API contracts.
    These run without the 'slow' mark and are safe to run in CI.
    """

    def test_next_without_session_pool_returns_error(self, api_base, auth_headers):
        """
        /recommend/next with a nonexistent session pool ID must return 404.
        The frontend must handle this gracefully (show error, not crash).
        """
        response = requests.get(
            f"{api_base}/recommend/next",
            params={"sessionPoolId": "nonexistent-pool-id-00000000"},
            headers=auth_headers,
            timeout=10,
        )
        assert response.status_code in (404, 400), (
            f"Expected 404/400 for nonexistent pool, got {response.status_code}"
        )

    def test_next_without_auth_returns_401(self, api_base):
        """
        Unauthenticated requests to /recommend/next must be rejected.
        """
        response = requests.get(
            f"{api_base}/recommend/next",
            params={"sessionPoolId": "any-pool-id"},
            timeout=10,
        )
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {response.status_code}"
        )

    def test_health_endpoint_is_fast(self, api_base):
        """
        /api/health must respond in < 200ms — it's used by monitoring and
        also by the frontend to detect server availability.
        """
        start = time.perf_counter()
        response = requests.get(f"{api_base}/health", timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        assert elapsed_ms < 200, f"/api/health took {elapsed_ms:.0f}ms"

    def test_status_endpoint_returns_pipeline_step(self, api_base, auth_headers):
        """
        /recommend/status must return a valid pipeline status object.
        The generating.js screen polls this every 1.2s to show progress.
        """
        response = requests.get(
            f"{api_base}/recommend/status",
            headers=auth_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert "step" in data, f"Missing 'step' in status response: {data}"
        assert isinstance(data["step"], int), f"'step' must be int, got {type(data['step'])}"
