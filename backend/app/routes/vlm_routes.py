"""
VLM (Vision Language Model) routes for ingredient identification.
"""

import io
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from app.schemas import VlmResponse, IngredientItem, ErrorResponse
from app.auth import get_current_user_id
from app.services.vlm_service import identify_ingredients

router = APIRouter(prefix="/api/vlm", tags=["vlm"])


@router.post("/identify", response_model=VlmResponse)
async def identify(
    images: list[UploadFile] = File(...),
    user_id: str = Depends(get_current_user_id),
):
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required")

    if len(images) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 images allowed")

    image_bytes_list = []
    for img in images:
        content = await img.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image exceeds 10MB limit")
        image_bytes_list.append(content)

    try:
        ingredients = await identify_ingredients(image_bytes_list)
        return VlmResponse(ingredients=ingredients)
    except TimeoutError:
        return VlmResponse(ingredients=[])
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="VLM service unavailable",
        )
