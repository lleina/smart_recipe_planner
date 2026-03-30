"""
Vision Language Model routes for ingredient identification from photos.

Accepts up to 5 images per request. Each image is passed to the configured
VLM (default: Qwen3-VL 4B via Ollama) which identifies the ingredients
visible in the photo along with confidence, category, urgency, and quantity.

Image constraints:
    - Maximum 5 images per request
    - Maximum 10 MB per image
    - Supported formats: JPEG, PNG, WebP
"""

import logging

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from app.auth import get_current_user_id
from app.schemas import IngredientItem, VlmResponse
from app.services.vlm_service import identify_ingredients

logger = logging.getLogger("app.vlm_routes")
router = APIRouter(prefix="/api/vlm", tags=["vlm"])

_MAX_IMAGES_PER_REQUEST = 5
_MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _image_size_error_response() -> JSONResponse:
    """Build a standardized 400 response for oversized image uploads."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "ERR_VLM_IMAGE_TOO_LARGE",
                "message": "One of your images exceeds 10 MB. Please use a smaller photo.",
                "retryable": False,
            }
        },
    )


@router.post("/identify", response_model=VlmResponse)
async def identify_ingredients_from_images(
    images: list[UploadFile] = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """Identify ingredients visible in one or more uploaded photos.

    Each image is passed to the vision model which returns a structured list
    of detected ingredients including confidence, category (perishable /
    shelf-stable / etc.), estimated urgency (days until spoilage), and
    approximate quantity.

    Falls back gracefully with a 503 when the VLM is unavailable — the
    frontend guides the user to add ingredients manually in that case.

    Args:
        images: 1–5 image files (JPEG, PNG, or WebP; max 10 MB each).
        user_id: Authenticated user's ID (used for logging only).

    Returns:
        ``VlmResponse`` with a list of ``IngredientItem`` objects.

    Raises:
        400 ERR_VLM_NO_IMAGES: If the request contains no images.
        400 ERR_VLM_TOO_MANY: If more than 5 images are uploaded.
        400 ERR_VLM_IMAGE_TOO_LARGE: If any image exceeds 10 MB.
        503 ERR_VLM_TIMEOUT: If the vision model is unavailable or times out.
    """
    if not images:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ERR_VLM_NO_IMAGES",
                    "message": "Please upload at least one photo of your ingredients.",
                    "retryable": False,
                }
            },
        )

    if len(images) > _MAX_IMAGES_PER_REQUEST:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ERR_VLM_TOO_MANY",
                    "message": f"You can upload up to {_MAX_IMAGES_PER_REQUEST} photos at a time.",
                    "retryable": False,
                }
            },
        )

    image_bytes_list: list[bytes] = []
    for uploaded_image in images:
        image_content = await uploaded_image.read()
        if len(image_content) > _MAX_IMAGE_SIZE_BYTES:
            return _image_size_error_response()
        image_bytes_list.append(image_content)

    try:
        detected_ingredients: list[IngredientItem] = await identify_ingredients(
            image_bytes_list
        )
        return VlmResponse(ingredients=detected_ingredients)
    except Exception as exc:  # pylint: disable=broad-except
        # Intentionally broad: VLM failures (timeout, model not loaded, parse
        # error) must never crash the request — the user falls back to manual entry.
        logger.warning(
            "VLM ingredient identification failed for user %s: %s",
            user_id[:8],
            exc,
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "ERR_VLM_TIMEOUT",
                    "message": (
                        "Something went wrong identifying your ingredients. "
                        "You can add them manually."
                    ),
                    "retryable": True,
                }
            },
        )
