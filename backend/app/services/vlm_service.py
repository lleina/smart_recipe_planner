"""
VLM service - identifies ingredients from images.

Uses Ollama's native /api/chat endpoint (NOT the OpenAI-compatible /v1)
so that:
  1. ``think: false`` is honoured — prevents thinking models (qwen3.5,
     deepseek-r1) from consuming all tokens on internal reasoning.
  2. Images are passed via the native ``images`` field (base64 list),
     which is more reliable than OpenAI-style image_url content blocks
     for local vision models.

Falls back to mock data when VLM_BASE_URL is not configured.
"""

import base64
import json
import logging
import re
from app.config import VLM_BASE_URL, VLM_MODEL, VLM_TIMEOUT_SECONDS, VLM_API_KEY
from app.services.inference_client import ollama_chat
from app.schemas import IngredientItem

logger = logging.getLogger("app.vlm")

VLM_PROMPT = (
    "Identify all visible food ingredients in this image. "
    "For each ingredient return a JSON object with exactly these fields: "
    "name (string), confidence (float 0-1), "
    "category (one of: perishable, semi-perishable, shelf-stable), "
    "urgency (integer days until spoilage based on visual cues and typical shelf life; "
    "null for shelf-stable items), "
    "estimatedQuantity (number, approximate count or amount visible), "
    "unit (one of: pieces, bags, bunches, lbs, cups, boxes, bottles, cans). "
    "Return ONLY a valid JSON array. No markdown, no explanation."
)

_CONFIDENCE_THRESHOLD = 0.5


async def identify_ingredients(image_bytes_list: list[bytes]) -> list[IngredientItem]:
    if not VLM_BASE_URL:
        logger.info("VLM_BASE_URL not set — returning mock ingredients")
        return _mock_ingredients()
    try:
        logger.info("Calling VLM (%s) with %d image(s)", VLM_MODEL, len(image_bytes_list))
        result = await _call_vlm(image_bytes_list)
        logger.info("VLM returned %d ingredients", len(result))
        return result
    except Exception as e:
        logger.warning("VLM call failed (%s: %s) — falling back to mock", type(e).__name__, e)
        return _mock_ingredients()


async def _call_vlm(image_bytes_list: list[bytes]) -> list[IngredientItem]:
    b64_images = [base64.b64encode(b).decode("utf-8") for b in image_bytes_list]

    raw_text = await ollama_chat(
        base_url=VLM_BASE_URL,
        model=VLM_MODEL,
        messages=[{"role": "user", "content": VLM_PROMPT, "images": b64_images}],
        max_tokens=2000,
        temperature=0.3,
        timeout=VLM_TIMEOUT_SECONDS,
        think=False,
    )

    clean = _extract_json(raw_text)
    return _parse_vlm_response(json.loads(clean))


def _extract_json(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        return match.group(0)
    return raw


def _parse_vlm_response(raw: list[dict]) -> list[IngredientItem]:
    # First pass: build filtered list
    parsed: list[IngredientItem] = []
    for item in raw:
        confidence = float(item.get("confidence", 0))
        if confidence < _CONFIDENCE_THRESHOLD:
            continue
        parsed.append(IngredientItem(
            name=str(item.get("name", "unknown")).lower().strip(),
            confidence=confidence,
            category=item.get("category", "shelf-stable"),
            urgency=item.get("urgency"),
            estimated_quantity=float(item.get("estimatedQuantity", 1)),
            unit=str(item.get("unit", "pieces")),
        ))

    # Second pass: deduplicate by name (case-insensitive).
    # Keep the entry with the highest confidence; average quantities across duplicates.
    seen: dict[str, IngredientItem] = {}
    quantities: dict[str, list[float]] = {}
    for item in parsed:
        key = item.name  # already lowercased above
        if key not in seen or item.confidence > seen[key].confidence:
            seen[key] = item
        quantities.setdefault(key, []).append(item.estimated_quantity)

    results = []
    for key, item in seen.items():
        avg_qty = sum(quantities[key]) / len(quantities[key])
        results.append(item.model_copy(update={"estimated_quantity": round(avg_qty, 2)}))

    return results


def _mock_ingredients() -> list[IngredientItem]:
    return [
        IngredientItem(name="tomato", confidence=0.95, category="perishable",
                       urgency=5, estimated_quantity=4, unit="pieces"),
        IngredientItem(name="onion", confidence=0.90, category="semi-perishable",
                       urgency=14, estimated_quantity=2, unit="pieces"),
        IngredientItem(name="chicken breast", confidence=0.88, category="perishable",
                       urgency=2, estimated_quantity=2, unit="pieces"),
        IngredientItem(name="rice", confidence=0.85, category="shelf-stable",
                       urgency=None, estimated_quantity=1, unit="bags"),
        IngredientItem(name="bell pepper", confidence=0.82, category="perishable",
                       urgency=7, estimated_quantity=2, unit="pieces"),
    ]
