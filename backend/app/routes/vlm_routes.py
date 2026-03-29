"""
VLM (Vision Language Model) routes for ingredient identification.
"""

import logging
from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from app.schemas import VlmResponse, IngredientItem
from app.auth import get_current_user_id
from app.services.vlm_service import identify_ingredients

logger = logging.getLogger("app.vlm_routes")
router = APIRouter(prefix="/api/vlm", tags=["vlm"])


@router.post("/identify", response_model=VlmResponse)
async def identify(
    images: list[UploadFile] = File(...),
    user_id: str = Depends(get_current_user_id),
):
    if not images:
        return JSONResponse(status_code=400, content={"error": {
            "code": "ERR_VLM_NO_IMAGES",
            "message": "Please upload at least one photo of your ingredients.",
            "retryable": False,
        }})

    if len(images) > 5:
        return JSONResponse(status_code=400, content={"error": {
            "code": "ERR_VLM_TOO_MANY",
            "message": "You can upload up to 5 photos at a time.",
            "retryable": False,
        }})

    image_bytes_list = []
    for img in images:
        content = await img.read()
        if len(content) > 10 * 1024 * 1024:
            return JSONResponse(status_code=400, content={"error": {
                "code": "ERR_VLM_IMAGE_TOO_LARGE",
                "message": "One of your images exceeds 10 MB. Please use a smaller photo.",
                "retryable": False,
            }})
        image_bytes_list.append(content)

    try:
        ingredients = await identify_ingredients(image_bytes_list)
        return VlmResponse(ingredients=ingredients)
    except Exception as e:
        logger.warning("VLM identify failed for user %s: %s", user_id[:8], e)
        return JSONResponse(status_code=503, content={"error": {
            "code": "ERR_VLM_TIMEOUT",
            "message": "Something went wrong identifying your ingredients. You can add them manually.",
            "retryable": True,
        }})
