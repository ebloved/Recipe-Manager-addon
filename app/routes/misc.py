"""Раздача статики, файлы, health."""
from __future__ import annotations

import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from config import (
    AUTH_MODE,
    DOWNLOAD_DIR,
    GEMINI_API_KEY,
    GEMINI_MODELS,
    STATIC_DIR,
)
from stores import meal_plan_store, recipe_store
from services.auth import get_current_user

router = APIRouter(tags=["misc"])

_MIME = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".md": "text/markdown; charset=utf-8",
    ".map": "application/json; charset=utf-8",
}


def _serve_static_file(rel_path: str) -> FileResponse:
    """Безопасно отдаёт файл из STATIC_DIR."""
    rel = Path(rel_path)
    # Защита от ../ и абсолютных путей
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise HTTPException(400, "Invalid path")

    full = (STATIC_DIR / rel).resolve()
    static_root = STATIC_DIR.resolve()
    # Убеждаемся, что не выходим за пределы STATIC_DIR
    try:
        full.relative_to(static_root)
    except ValueError:
        raise HTTPException(400, "Invalid path")

    if not full.exists() or not full.is_file():
        raise HTTPException(404, f"Not found: {rel_path}")

    media = _MIME.get(full.suffix.lower(), "application/octet-stream")
    return FileResponse(full, media_type=media)


# --- Static files (явный роут вместо mount) --------------------------------

@router.get("/static/{file_path:path}", include_in_schema=False)
async def serve_static(file_path: str):
    return _serve_static_file(file_path)

# --- Index ------------------------------------------------------------------


@router.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    fav = STATIC_DIR / "favicon.ico"
    if fav.exists():
        return FileResponse(fav)
    raise HTTPException(404, "Favicon not found")

@router.get("/", include_in_schema=False)
async def index(request: Request):
    # Если включен OAuth, проверяем подписанную сессию ДО отдачи HTML
    if AUTH_MODE == "oauth" and not get_current_user(request):
        return RedirectResponse(url="/api/auth/login")

    # Если всё ок (или AUTH_MODE=ha) — отдаем интерфейс
    async with aiofiles.open(STATIC_DIR / "index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(await f.read())

# --- SPA роут для публичных ссылок ------------------------------------------

@router.get("/share/{token}", response_class=HTMLResponse, include_in_schema=False)
async def share_page(request: Request, token: str):
    """Отдельная публичная страница рецепта (без SPA)."""
    from services.share_view import (
        render_share_not_found,
        render_share_page,
        share_headers,
    )

    recipe = recipe_store.get_by_share_token(token)
    headers = share_headers()
    if not recipe:
        return HTMLResponse(
            render_share_not_found(), status_code=404, headers=headers
        )
    share_url = str(request.url).split("?", 1)[0]
    return HTMLResponse(
        render_share_page(recipe, share_url), headers=headers
    )


# --- Скачанные файлы (рецепты из YouTube) -----------------------------------

@router.get("/files/{filename}")
async def get_file(request: Request, filename: str):
    if AUTH_MODE == "oauth" and not get_current_user(request):
        raise HTTPException(401, "Unauthorized")
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


# --- Health и диагностика ---------------------------------------------------

@router.get("/api/health")
async def health():
    """Публичный healthcheck: без внутренних данных."""
    return {"status": "ok"}


@router.get("/api/health/details")
async def health_details(request: Request):
    """Диагностика для админа: модели, наличие ключа, размеры данных."""
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return {
        "status": "ok",
        "models": GEMINI_MODELS,
        "api_key": bool(GEMINI_API_KEY),
        "recipes": len(recipe_store.recipes),
        "meal_plan_entries": len(meal_plan_store.entries),
    }


@router.get("/api/debug/static")
async def debug_static(request: Request):
    """Показывает, где сервер ищет статику и что там лежит."""
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    def listdir(p: Path) -> list[str]:
        try:
            return sorted(os.listdir(p))
        except Exception as e:  # noqa: BLE001
            return [f"ERROR: {e}"]

    return {
        "STATIC_DIR": str(STATIC_DIR),
        "STATIC_DIR_exists": STATIC_DIR.exists(),
        "STATIC_DIR_contents": listdir(STATIC_DIR) if STATIC_DIR.exists() else [],
        "css_dir_exists": (STATIC_DIR / "css").exists(),
        "css_contents": listdir(STATIC_DIR / "css") if (STATIC_DIR / "css").exists() else [],
        "js_dir_exists": (STATIC_DIR / "js").exists(),
        "js_contents": listdir(STATIC_DIR / "js") if (STATIC_DIR / "js").exists() else [],
        "index_exists": (STATIC_DIR / "index.html").exists(),
        "style_exists": (STATIC_DIR / "css" / "style.css").exists(),
        "utils_exists": (STATIC_DIR / "js" / "utils.js").exists(),
        "cwd": os.getcwd(),
    }