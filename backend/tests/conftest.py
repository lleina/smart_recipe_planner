"""
Shared pytest fixtures for backend integration tests.

Prerequisites (all must be running before executing the test suite):
  1. FastAPI backend:   uvicorn app.main:app --reload  (port 8000)
  2. Ollama LLM:        ollama serve  (with qwen3:4b pulled)
  3. Ollama VLM:        ollama serve  (with qwen3-vl:4b pulled — needed for VLM tests only)

Run the full suite:
  cd backend && pytest tests/ -v

Skip slow integration tests (LLM pipeline):
  cd backend && pytest tests/ -v -m "not slow"

Skip VLM tests (no image model loaded):
  cd backend && pytest tests/ -v -m "not vlm"
"""

import time
import pytest
import requests

BASE_URL = "http://localhost:8000"
API_URL = f"{BASE_URL}/api"

# ── Session-scoped client ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def api_base():
    """Returns the base API URL and verifies the backend is reachable."""
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {BASE_URL}: {exc}")
    return API_URL


# ── Auth fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def registered_user(api_base):
    """
    Registers a fresh test user and returns (user_id, access_token).

    Scoped to the module so all tests in a file share one user — avoids
    creating hundreds of throwaway accounts in the database.
    """
    email = f"test_{int(time.time() * 1000)}@pytest.local"
    password = "pytest-test-password-123"

    response = requests.post(
        f"{api_base}/auth/register",
        json={"email": email, "password": password},
        timeout=10,
    )
    assert response.status_code == 200, (
        f"Registration failed: {response.status_code} — {response.text}"
    )

    data = response.json()
    return data["userId"], data["accessToken"]


@pytest.fixture(scope="module")
def auth_headers(registered_user):
    """Returns Authorization headers for the test user."""
    _, access_token = registered_user
    return {"Authorization": f"Bearer {access_token}"}


# ── Session pool fixture ─────────────────────────────────────────────────────

# Standard test session context — small and fast
TEST_SESSION_CONTEXT = {
    "mealType": "dinner",
    "availableTimeMinutes": 30,
    "servingCount": 2,
    "occasion": "",
    "availableIngredients": [
        {"name": "chicken breast", "estimatedQuantity": 2.0, "unit": "pieces", "urgency": 2},
        {"name": "rice", "estimatedQuantity": 1.0, "unit": "cups", "urgency": None},
        {"name": "broccoli", "estimatedQuantity": 1.0, "unit": "head", "urgency": 3},
        {"name": "soy sauce", "estimatedQuantity": 0.25, "unit": "cups", "urgency": None},
        {"name": "garlic", "estimatedQuantity": 3.0, "unit": "cloves", "urgency": None},
    ],
}


@pytest.fixture(scope="module")
def active_session_pool(api_base, registered_user, auth_headers):
    """
    Runs the full recipe pipeline once per test module and returns the pool data.

    This is a slow fixture (LLM + web fetch) but is shared across all tests
    in a module to avoid running the expensive pipeline multiple times.

    Marked with pytest.mark.slow — skip with: pytest -m "not slow"
    """
    user_id, _ = registered_user

    print(f"\n[conftest] Starting recommendation pipeline for user {user_id}…")
    start = time.time()

    response = requests.post(
        f"{api_base}/recommend",
        json={"userId": user_id, "sessionContext": TEST_SESSION_CONTEXT},
        headers=auth_headers,
        timeout=660,  # LLM pipeline can take up to 11 min
    )
    elapsed = time.time() - start

    assert response.status_code == 200, (
        f"Pipeline failed: {response.status_code} — {response.text[:500]}"
    )

    data = response.json()
    print(f"[conftest] Pipeline completed in {elapsed:.1f}s — "
          f"poolSize={data.get('poolSize')}, recipes={len(data.get('recipes', []))}")

    assert data.get("sessionPoolId"), "Response missing sessionPoolId"
    assert len(data.get("recipes", [])) >= 1, "Pipeline returned no recipes"

    return data
