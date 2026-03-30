"""
VLM service — identifies food ingredients from uploaded images.

Uses Ollama's native ``/api/chat`` endpoint (not the OpenAI-compatible ``/v1``)
because:
  1. ``think: false`` is only honoured by the native endpoint, preventing
     thinking models (qwen3, deepseek-r1) from consuming all tokens on
     internal reasoning with an empty content response.
  2. Images are passed via the native ``images`` field (base64 list), which
     is more reliable for local vision models than OpenAI-style image_url
     content blocks.

Falls back to a small set of mock ingredients when ``VLM_BASE_URL`` is not
configured, enabling frontend development without a running Ollama instance.
"""

import base64
import json
import logging
import re

from app.config import VLM_API_KEY, VLM_BASE_URL, VLM_MODEL, VLM_TIMEOUT_SECONDS
from app.schemas import IngredientItem
from app.services.inference_client import ollama_chat

logger = logging.getLogger("app.vlm")

# Minimum confidence score below which a VLM detection is discarded.
# Reduces hallucinated or low-quality identifications.
_CONFIDENCE_THRESHOLD = 0.55

# Prompt instructing the VLM to return only food ingredients as a JSON array.
_IDENTIFICATION_PROMPT = (
    "Look at this image and identify ONLY the food and drink ingredients that are visible. "
    "DO NOT include bowls, plates, pots, pans, cups, glasses, mugs, utensils, knives, forks, "
    "spoons, spatulas, cutting boards, trays, racks, containers, packaging, bags, wrappers, "
    "labels, paper, cloth, towels, napkins, or any non-food object. "
    "If you are not certain something is a food or drink ingredient, do NOT include it. "
    "For each FOOD OR DRINK INGREDIENT ONLY return a JSON object with exactly these fields: "
    "name (string — ingredient name only, e.g. 'chicken breast', 'onion', 'olive oil'), "
    "confidence (float 0-1), "
    "category (one of: perishable, semi-perishable, shelf-stable), "
    "urgency (integer days until spoilage based on visual cues and typical shelf life; "
    "null for shelf-stable items), "
    "estimatedQuantity (number, approximate count or amount visible), "
    "unit (one of: pieces, bags, bunches, lbs, cups, boxes, bottles, cans). "
    "Return ONLY a valid JSON array of food ingredients. No markdown, no explanation."
)

# Substrings that indicate a VLM "ingredient" is actually a non-food object.
# Used as a post-filter to catch hallucinations the confidence threshold misses.
_NON_FOOD_SUBSTRINGS: set[str] = {
    "bowl", "plate", "pan", "pot", "cup", "glass", "mug", "knife", "fork", "spoon",
    "spatula", "ladle", "tongs", "whisk", "peeler", "grater", "cutting board",
    "container", "packaging", "wrapper", "bag clip", "label", "lid", "cap",
    "utensil", "tray", "rack", "sheet", "napkin", "towel", "cloth", "paper",
    "dish", "skillet", "wok", "colander", "strainer", "measuring cup", "mixing bowl",
}


async def identify_ingredients(image_bytes_list: list[bytes]) -> list[IngredientItem]:
    """Identify food ingredients visible in one or more images.

    Delegates to the VLM when ``VLM_BASE_URL`` is configured; returns a
    small set of mock ingredients otherwise (useful for frontend development
    without Ollama running).

    Args:
        image_bytes_list: List of raw image bytes (JPEG, PNG, or WebP).

    Returns:
        List of ``IngredientItem`` objects, deduplicated by name and filtered
        by confidence. Returns mock data if the VLM is unavailable.
    """
    if not VLM_BASE_URL:
        logger.info("VLM_BASE_URL not configured — returning mock ingredients")
        return _build_mock_ingredients()

    try:
        logger.info(
            "Calling VLM (%s) with %d image(s)", VLM_MODEL, len(image_bytes_list)
        )
        detected_ingredients = await _call_vlm_and_parse(image_bytes_list)
        logger.info("VLM identified %d ingredients", len(detected_ingredients))
        return detected_ingredients
    except Exception as exc:  # pylint: disable=broad-except
        # VLM failures must never propagate to the caller — the route handler
        # catches them separately, but we also want a clean fallback here.
        logger.warning(
            "VLM call failed (%s: %s) — returning mock ingredients as fallback",
            type(exc).__name__,
            exc,
        )
        return _build_mock_ingredients()


async def _call_vlm_and_parse(image_bytes_list: list[bytes]) -> list[IngredientItem]:
    """Encode images as base64, call the VLM, and parse the JSON response.

    Args:
        image_bytes_list: Raw image bytes to send to the VLM.

    Returns:
        Parsed, filtered, and deduplicated list of ``IngredientItem`` objects.

    Raises:
        ValueError: If the VLM returns empty content or unparseable JSON.
        httpx.TimeoutException: If the VLM call exceeds ``VLM_TIMEOUT_SECONDS``.
    """
    base64_images = [
        base64.b64encode(image_bytes).decode("utf-8")
        for image_bytes in image_bytes_list
    ]

    raw_response_text = await ollama_chat(
        base_url=VLM_BASE_URL,
        model=VLM_MODEL,
        messages=[{
            "role": "user",
            "content": _IDENTIFICATION_PROMPT,
            "images": base64_images,
        }],
        max_tokens=2000,
        temperature=0.3,
        timeout=VLM_TIMEOUT_SECONDS,
        think=False,
    )

    json_text = _extract_json_array(raw_response_text)
    raw_ingredient_dicts: list[dict] = json.loads(json_text)
    return _filter_and_deduplicate(raw_ingredient_dicts)


def _extract_json_array(raw_text: str) -> str:
    """Strip LLM wrapper text (think blocks, markdown fences) to get the JSON array.

    Args:
        raw_text: Raw text output from the VLM, which may include ``<think>``
            blocks or markdown code fences around the JSON.

    Returns:
        A string containing only the JSON array, ready for ``json.loads``.
    """
    # Remove chain-of-thought reasoning blocks emitted by thinking models.
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)
    cleaned = (
        cleaned.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    json_array_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if json_array_match:
        return json_array_match.group(0)
    return cleaned


def _filter_and_deduplicate(raw_items: list[dict]) -> list[IngredientItem]:
    """Filter low-confidence and non-food items, then deduplicate by name.

    Filtering rules:
    - Confidence below ``_CONFIDENCE_THRESHOLD`` → discarded.
    - Name contains any ``_NON_FOOD_SUBSTRINGS`` → discarded.
    - Duplicates by name → keep highest-confidence entry; average quantities.

    Args:
        raw_items: Raw dicts from the VLM JSON response.

    Returns:
        Cleaned, deduplicated list of ``IngredientItem`` objects.
    """
    high_confidence_items: list[IngredientItem] = []

    for raw_item in raw_items:
        detection_confidence = float(raw_item.get("confidence", 0))
        if detection_confidence < _CONFIDENCE_THRESHOLD:
            continue

        ingredient_name = str(raw_item.get("name", "unknown")).lower().strip()

        if any(non_food in ingredient_name for non_food in _NON_FOOD_SUBSTRINGS):
            logger.debug("Filtered non-food VLM detection: %r", ingredient_name)
            continue

        high_confidence_items.append(IngredientItem(
            name=ingredient_name,
            confidence=detection_confidence,
            category=raw_item.get("category", "shelf-stable"),
            urgency=raw_item.get("urgency"),
            estimated_quantity=float(raw_item.get("estimatedQuantity", 1)),
            unit=str(raw_item.get("unit", "pieces")),
        ))

    # Deduplicate: keep the highest-confidence entry per ingredient name;
    # average the estimated quantities across all detections of that name.
    best_by_name: dict[str, IngredientItem] = {}
    quantities_by_name: dict[str, list[float]] = {}

    for ingredient in high_confidence_items:
        name_key = ingredient.name
        if name_key not in best_by_name or ingredient.confidence > best_by_name[name_key].confidence:
            best_by_name[name_key] = ingredient
        quantities_by_name.setdefault(name_key, []).append(ingredient.estimated_quantity)

    deduplicated_ingredients: list[IngredientItem] = []
    for name_key, best_ingredient in best_by_name.items():
        average_quantity = sum(quantities_by_name[name_key]) / len(quantities_by_name[name_key])
        deduplicated_ingredients.append(
            best_ingredient.model_copy(update={"estimated_quantity": round(average_quantity, 2)})
        )

    return deduplicated_ingredients


def _build_mock_ingredients() -> list[IngredientItem]:
    """Return a fixed set of mock ingredients for development without a VLM.

    Returns:
        A representative list of ``IngredientItem`` objects covering
        perishable, semi-perishable, and shelf-stable categories.
    """
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
