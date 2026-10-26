"""Раздача статики, файлы, health."""
from __future__ import annotations

import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from config import (
    AUTH_MODE,
    DOWNLOAD_DIR,
    GEMINI_API_KEY,
    GEMINI_MODELS,
    STATIC_DIR,
)
from stores import meal_plan_store, recipe_store
from services.auth import users_store

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

@router.get("/share/static/{file_path:path}", include_in_schema=False)
async def serve_static_share(file_path: str):
    """Отдаёт статику для SPA-страниц /share/..."""
    return _serve_static_file(file_path)


# --- Index ------------------------------------------------------------------

from fastapi import Request


@router.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    fav = STATIC_DIR / "favicon.ico"
    if fav.exists():
        return FileResponse(fav)
    raise HTTPException(404, "Favicon not found")

@router.get("/", include_in_schema=False)
async def index(request: Request):
    # Если включен OAuth, проверяем куку ДО отдачи HTML
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            # Отправляем на Google OAuth
            return RedirectResponse(url="/api/auth/login")
            
    # Если всё ок (или AUTH_MODE=ha) — отдаем интерфейс
    async with aiofiles.open(STATIC_DIR / "index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(await f.read())

# --- SPA роут для публичных ссылок ------------------------------------------

@router.get("/share/{token}", response_class=HTMLResponse, include_in_schema=False)
async def share_spa(token: str):
    """Отдаёт index.html для ссылки /share/<token>, чтобы JS сам подхватил токен."""
    async with aiofiles.open(STATIC_DIR / "index.html", "r", encoding="utf-8") as f:
        html = await f.read()
    
    # v2.6.6: Добавляем <base href="../../">, чтобы относительные пути
    # (static/css/... и static/js/...) корректно резолвились в корень.
    # Это работает и для Standalone (/share/token), и для HA ingress (/api/hassio_ingress/.../share/token)
    if "<head>" in html and "<base" not in html:
        html = html.replace("<head>", "<head>\n<base href='../../'>")
        
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )



# --- Скачанные файлы (рецепты из YouTube) -----------------------------------

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


# --- Health и диагностика ---------------------------------------------------

@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "models": GEMINI_MODELS,
        "api_key": bool(GEMINI_API_KEY),
        "recipes": len(recipe_store.recipes),
        "meal_plan_entries": len(meal_plan_store.entries),
    }


@router.get("/api/debug/static")
async def debug_static():
    """Показывает, где сервер ищет статику и что там лежит."""
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