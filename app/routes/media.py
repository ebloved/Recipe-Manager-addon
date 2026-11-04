"""Загрузка и раздача изображений рецептов."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi import Request

from services import media_store
from services.auth import get_current_user

router = APIRouter(tags=["media"])


@router.post("/api/media/image")
async def upload_media_image(request: Request, file: UploadFile = File(...)):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Unauthorized")

    data = await file.read(media_store.MAX_UPLOAD_BYTES + 1)
    if len(data) > media_store.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file is too large (max 15 MB)")
    try:
        image = await media_store.save_image(data)
    except media_store.MediaError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"image": image}


@router.get("/media/{digest}/{filename}")
async def get_media_image(digest: str, filename: str):
    if not filename.endswith(".webp"):
        raise HTTPException(404, "Not found")
    variant = filename[:-5]
    path = media_store.variant_path(digest, variant)
    if path is None:
        raise HTTPException(404, "Not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
