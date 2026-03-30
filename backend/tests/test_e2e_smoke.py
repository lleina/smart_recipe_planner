"""
End-to-end smoke test: register → recommend → verify.

This is the original e2e_test.py, ported to pytest for consistent test
output and integration with the rest of the test suite.  The test still
prints a detailed summary (like the original script) but now fails with a
clear pytest assertion rather than sys.exit(1).

Run standalone:
  cd backend && pytest tests/test_e2e_smoke.py -v -s

Run as part of the full suite:
  cd backend && pytest tests/ -v

Mark: 'slow' (runs the full LLM pipeline).
"""

import time
import pytest
import requests


@pytest.mark.slow
class TestE2ESmokeTest:
    """
    Full-stack smoke test that exercises every major API endpoint in sequence.

    Deliberately does NOT share the active_session_pool fixture — it runs its
    own pipeline so it can validate the complete flow from a fresh user, giving
    an isolated signal that the entire system is healthy end-to-end.
    """

    def test_full_pipeline_flow(self, api_base):
        """
        Runs the complete user journey:
          1. Register new user
          2. Health check
          3. Call /recommend (full pipeline)
          4. Verify recipe shape and field presence
          5. Fetch one recipe by ID
          6. Fetch next batch

        If any step fails, subsequent steps are skipped automatically.
        """
        base = api_base

        # ── Step 1: Register ────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("STEP 1: Register a new user")
        print("=" * 60)
        email = f"smoke_{int(time.time())}@test.local"
        reg = requests.post(
            f"{base}/auth/register",
            json={"email": email, "password": "smoketest123"},
            timeout=10,
        )
        print(f"  Status: {reg.status_code}")
        assert reg.status_code == 200, f"Registration failed: {reg.text}"

        reg_data = reg.json()
        token = reg_data["accessToken"]
        user_id = reg_data["userId"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"  userId: {user_id}")

        # ── Step 2: Health check ────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("STEP 2: Health check")
        print("=" * 60)
        health = requests.get(f"{base}/health", timeout=5)
        print(f"  Status: {health.status_code} — {health.json()}")
        assert health.status_code == 200

        # ── Step 3: Call /recommend ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("STEP 3: Call /recommend (full LLM + web pipeline)")
        print("=" * 60)
        payload = {
            "userId": user_id,
            "sessionContext": {
                "mealType": "dinner",
                "availableTimeMinutes": 45,
                "servingCount": 2,
                "occasion": "",
                "availableIngredients": [
                    {"name": "chicken breast", "estimatedQuantity": 2.0, "unit": "pieces", "urgency": 2},
                    {"name": "rice", "estimatedQuantity": 1.0, "unit": "cups", "urgency": None},
                    {"name": "broccoli", "estimatedQuantity": 1.0, "unit": "head", "urgency": 3},
                    {"name": "soy sauce", "estimatedQuantity": 0.5, "unit": "cups", "urgency": None},
                    {"name": "garlic", "estimatedQuantity": 4.0, "unit": "cloves", "urgency": None},
                ],
            },
        }
        print(f"  Sending POST to {base}/recommend …")
        pipeline_start = time.time()
        rec = requests.post(
            f"{base}/recommend",
            json=payload,
            headers=headers,
            timeout=660,
        )
        pipeline_elapsed = time.time() - pipeline_start
        print(f"  Status: {rec.status_code} (took {pipeline_elapsed:.1f}s)")

        assert rec.status_code == 200, f"Pipeline failed: {rec.text[:500]}"
        rec_data = rec.json()
        session_pool_id = rec_data.get("sessionPoolId")
        recipes = rec_data.get("recipes", [])

        print(f"  sessionPoolId: {session_pool_id}")
        print(f"  poolSize:      {rec_data.get('poolSize')}")
        print(f"  shownCount:    {rec_data.get('shownCount')}")
        print(f"  rankingMode:   {rec_data.get('rankingModeUsed')}")
        print(f"  recipes count: {len(recipes)}")

        assert session_pool_id, "Missing sessionPoolId"
        assert len(recipes) >= 1, "No recipes returned"

        # ── Step 4: Verify first 3 recipes ─────────────────────────────────
        print("\n" + "=" * 60)
        print("STEP 4: Recipe details (first 3)")
        print("=" * 60)
        for i, recipe in enumerate(recipes[:3]):
            print(f"  [{i + 1}] {recipe.get('title', 'NO TITLE')}")
            print(f"      id:          {recipe.get('id', 'MISSING')}")
            print(f"      totalTime:   {recipe.get('totalTime', 'MISSING')} min")
            print(f"      difficulty:  {recipe.get('difficulty', 'MISSING')}")
            print(f"      ingredients: {len(recipe.get('ingredients', []))} items")
            print(f"      steps:       {len(recipe.get('instructions', []))} steps")

            assert recipe.get("id"), f"Recipe [{i + 1}] missing id"
            assert recipe.get("title"), f"Recipe [{i + 1}] missing title"
            assert recipe.get("ingredients"), f"Recipe [{i + 1}] missing ingredients"
            assert recipe.get("instructions"), f"Recipe [{i + 1}] missing instructions"

        # ── Step 5: Fetch recipe by ID ──────────────────────────────────────
        print("\n" + "=" * 60)
        print("STEP 5: Fetch recipe by ID")
        print("=" * 60)
        first_id = recipes[0]["id"]
        detail = requests.get(
            f"{base}/recipes/{first_id}",
            headers=headers,
            timeout=10,
        )
        print(f"  GET /recipes/{first_id}: {detail.status_code}")
        assert detail.status_code == 200, f"Recipe detail failed: {detail.text[:300]}"

        # ── Step 6: Get next batch ──────────────────────────────────────────
        print("\n" + "=" * 60)
        print("STEP 6: Get next batch (/recommend/next)")
        print("=" * 60)
        next_start = time.perf_counter()
        next_resp = requests.get(
            f"{base}/recommend/next",
            params={"sessionPoolId": session_pool_id},
            headers=headers,
            timeout=10,
        )
        next_elapsed_ms = (time.perf_counter() - next_start) * 1000
        print(f"  Status: {next_resp.status_code} ({next_elapsed_ms:.0f}ms)")
        assert next_resp.status_code == 200, f"/recommend/next failed: {next_resp.text[:300]}"
        assert next_elapsed_ms < 1000, (
            f"/recommend/next took {next_elapsed_ms:.0f}ms — exceeds 1s SLA"
        )

        # ── Summary ─────────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print(f"✅ SMOKE TEST PASS — {len(recipes)} recipes in {pipeline_elapsed:.1f}s")
        print(f"   /recommend/next: {next_elapsed_ms:.0f}ms (SLA: <1000ms)")
        print("=" * 60)
