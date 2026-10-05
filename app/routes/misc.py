"""Раздача статики, файлы, health."""
from __future__ import annotations

from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from config import (
    DOWNLOAD_DIR,
    GEMINI_API_KEY,
    GEMINI_MODELS,
    STATIC_DIR,
)
from stores import meal_plan_store, recipe_store

router = APIRouter(tags=["misc"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    async with aiofiles.open(STATIC_DIR / "index.html", "r", encoding="utf-8") as f:
        return await f.read()


@router.get("/editor.js", include_in_schema=False)
async def serve_editor_js():
    return FileResponse(STATIC_DIR / "js" / "editor.js", media_type="application/javascript")


@router.get("/files/{filename}")
async def get_file(filename: str):
    safe = Path(filename).name
    path = DOWNLOAD_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    if safe.endswith(".md"):
        media = "text/markdown; charset=utf-8"
    elif safe.endswith(".srt"):
        media = "application/x-subrip"
    elif safe.endswith(".vtt"):
        media = "text/vtt; charset=utf-8"
    else:
        media = "application/octet-stream"
    return FileResponse(path, media_type=media, filename=safe)


@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "models": GEMINI_MODELS,
        "api_key": bool(GEMINI_API_KEY),
        "recipes": len(recipe_store.recipes),
        "meal_plan_entries": len(meal_plan_store.entries),
    }