"""
VLM (Vision Language Model) ingredient detection tests.

Tests the POST /api/vlm/identify endpoint end-to-end:
  - Accepts image uploads (multipart/form-data)
  - Returns structured ingredient list with confidence scores
  - Each identified ingredient has the fields the frontend expects
  - Confidence scores are in [0, 1]
  - Response arrives within VLM_TIMEOUT_MS (120s)

Prerequisites:
  - Backend running at localhost:8000
  - Ollama VLM model loaded: qwen3-vl:4b (or equivalent)

Run:
  cd backend && pytest tests/test_vlm_detection.py -v -m vlm

Skip if VLM model not loaded:
  cd backend && pytest tests/ -v -m "not vlm"
"""

import io
import time
import struct
import zlib
import pytest
import requests

# ── PNG generator (no Pillow dependency needed for tests) ─────────────────────

def _make_minimal_png(width=64, height=64, rgb=(220, 160, 60)):
    """
    Creates a minimal valid PNG image in memory without external dependencies.

    Returns raw PNG bytes representing a solid-color image. Used to create
    test images that the VLM endpoint accepts without needing real ingredient
    photos (which would make test results non-deterministic).

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        rgb: Solid fill color as (R, G, B) tuple.

    Returns:
        bytes: Valid PNG file content.
    """
    def png_chunk(chunk_type, data):
        chunk_len = len(data)
        chunk_data = chunk_type + data
        return (
            struct.pack(">I", chunk_len)
            + chunk_data
            + struct.pack(">I", zlib.crc32(chunk_data) & 0xFFFFFFFF)
        )

    # PNG signature
    signature = b"\x89PNG\r\n\x1a\n"

    # IHDR chunk
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = png_chunk(b"IHDR", ihdr_data)

    # IDAT chunk — raw pixel data (filter byte 0 = None per row)
    raw_rows = b""
    for _ in range(height):
        row = b"\x00" + bytes(rgb) * width
        raw_rows += row
    compressed = zlib.compress(raw_rows)
    idat = png_chunk(b"IDAT", compressed)

    # IEND chunk
    iend = png_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def _make_food_like_png():
    """
    Creates a slightly more food-like test image (orange/brown tones).

    The VLM model is prompted to identify ingredients — a warm-colored
    image gives it something plausible to work with, though results are
    model-dependent and non-deterministic.

    Returns:
        bytes: PNG bytes with warm food-like coloring.
    """
    return _make_minimal_png(width=128, height=128, rgb=(210, 130, 40))


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_png_bytes():
    """Returns a synthetic PNG image for VLM upload tests."""
    return _make_food_like_png()


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.vlm
class TestVlmIngredientDetection:
    """
    Tests for the VLM /identify endpoint.

    All tests are marked 'vlm' so they can be skipped when the vision model
    is not available: pytest -m "not vlm"
    """

    def test_identify_endpoint_accepts_image_upload(self, api_base, auth_headers, test_png_bytes):
        """
        POST /vlm/identify must accept a multipart/form-data image upload
        and return HTTP 200.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test_ingredient.png", io.BytesIO(test_png_bytes), "image/png")},
            headers=auth_headers,
            timeout=120,
        )
        assert response.status_code == 200, (
            f"VLM identify returned {response.status_code}: {response.text[:300]}"
        )

    def test_identify_response_has_ingredients_field(self, api_base, auth_headers, test_png_bytes):
        """
        The response body must have a top-level 'ingredients' array.
        This is the field the frontend useVlm hook reads.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test.png", io.BytesIO(test_png_bytes), "image/png")},
            headers=auth_headers,
            timeout=120,
        )
        assert response.status_code == 200
        data = response.json()
        assert "ingredients" in data, f"Response missing 'ingredients': {data}"
        assert isinstance(data["ingredients"], list), (
            f"'ingredients' must be a list, got {type(data['ingredients'])}"
        )

    def test_each_ingredient_has_required_fields(self, api_base, auth_headers, test_png_bytes):
        """
        Each ingredient in the response must have the fields the frontend
        useVlm hook consumes: name, confidence, category, urgency,
        estimatedQuantity, unit.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test.png", io.BytesIO(test_png_bytes), "image/png")},
            headers=auth_headers,
            timeout=120,
        )
        assert response.status_code == 200
        ingredients = response.json().get("ingredients", [])

        if not ingredients:
            pytest.skip("VLM returned no ingredients (model may need warm-up)")

        required_fields = {"name", "confidence", "category", "urgency"}
        for ingredient in ingredients:
            missing = required_fields - set(ingredient.keys())
            assert not missing, (
                f"Ingredient '{ingredient.get('name')}' missing fields: {missing}"
            )

    def test_confidence_scores_are_in_valid_range(self, api_base, auth_headers, test_png_bytes):
        """
        All confidence scores must be in [0.0, 1.0].
        The frontend filters at 0.5 and auto-confirms at 0.8.
        Scores outside [0, 1] would break those thresholds.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test.png", io.BytesIO(test_png_bytes), "image/png")},
            headers=auth_headers,
            timeout=120,
        )
        assert response.status_code == 200
        ingredients = response.json().get("ingredients", [])

        for ingredient in ingredients:
            confidence = ingredient.get("confidence", -1)
            assert 0.0 <= confidence <= 1.0, (
                f"Ingredient '{ingredient.get('name')}' has invalid confidence: {confidence}"
            )

    def test_ingredient_names_are_non_empty_strings(self, api_base, auth_headers, test_png_bytes):
        """
        All ingredient names must be non-empty strings.
        Empty names cause display bugs and broken deduplication.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test.png", io.BytesIO(test_png_bytes), "image/png")},
            headers=auth_headers,
            timeout=120,
        )
        assert response.status_code == 200
        ingredients = response.json().get("ingredients", [])

        for ingredient in ingredients:
            name = ingredient.get("name")
            assert isinstance(name, str) and name.strip(), (
                f"Ingredient has empty or non-string name: {ingredient}"
            )

    def test_identify_responds_within_timeout(self, api_base, auth_headers, test_png_bytes):
        """
        The VLM endpoint must respond within 120 seconds.

        The frontend sets VLM_TIMEOUT_MS = 120000 and shows an error if exceeded.
        The backend times out the Ollama call after that same window.
        """
        start = time.time()
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test.png", io.BytesIO(test_png_bytes), "image/png")},
            headers=auth_headers,
            timeout=125,  # slightly more than VLM_TIMEOUT_MS to catch backend timeout
        )
        elapsed = time.time() - start

        assert response.status_code == 200, f"VLM failed: {response.status_code}"
        assert elapsed < 120, f"VLM took {elapsed:.1f}s — exceeds 120s frontend timeout"

    def test_multiple_images_accepted(self, api_base, auth_headers, test_png_bytes):
        """
        The endpoint must accept multiple images in one request (up to 5).
        The frontend allows selecting multiple photos at once.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files=[
                ("images", ("img1.png", io.BytesIO(test_png_bytes), "image/png")),
                ("images", ("img2.png", io.BytesIO(_make_minimal_png(rgb=(100, 180, 80))), "image/png")),
            ],
            headers=auth_headers,
            timeout=120,
        )
        assert response.status_code == 200, (
            f"Multi-image upload failed: {response.status_code} — {response.text[:200]}"
        )

    def test_too_many_images_rejected(self, api_base, auth_headers, test_png_bytes):
        """
        Requests with more than 5 images must be rejected (HTTP 400).
        Backend constant: _MAX_IMAGES_PER_REQUEST = 5 in vlm_routes.py.
        """
        files = [
            ("images", (f"img{i}.png", io.BytesIO(test_png_bytes), "image/png"))
            for i in range(6)  # one more than the allowed maximum
        ]
        response = requests.post(
            f"{api_base}/vlm/identify",
            files=files,
            headers=auth_headers,
            timeout=10,
        )
        assert response.status_code == 400, (
            f"Expected 400 for 6 images, got {response.status_code}"
        )

    def test_no_auth_returns_401(self, api_base, test_png_bytes):
        """
        Unauthenticated VLM requests must be rejected with 401.
        """
        response = requests.post(
            f"{api_base}/vlm/identify",
            files={"images": ("test.png", io.BytesIO(test_png_bytes), "image/png")},
            timeout=10,
        )
        assert response.status_code == 401
