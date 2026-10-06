"""Recipe Manager — FastAPI backend для HA add-on.

Здесь только:
  - создание app
  - lifespan (загрузка stores + запуск backup scheduler)
  - middleware (CORS + ingress)
  - include_router
  - маршрут раздачи статики

Вся логика — в модулях routes/, services/, stores/.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import STATIC_DIR
from routes import api_router
from services.backup import backup_manager
from stores import (
    ingredients_store,
    meal_plan_store,
    recipe_store,
    shopping_store,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MIME-таблица для явной раздачи статики (под HA ingress StaticFiles mount
# может отдавать неверные MIME-типы, поэтому статика раздаётся своим роутом)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Загрузка хранилищ ---
    await recipe_store.load()
    await meal_plan_store.load()
    await shopping_store.load()
    await ingredients_store.load()

    logger.info("[recipes] loaded %d recipes", len(recipe_store.recipes))
    logger.info("[meal-plan] loaded %d entries", len(meal_plan_store.entries))
    logger.info("[shopping] loaded %d items", len(shopping_store.items))
    logger.info("[ingredients] loaded %d products", ingredients_store.count())

    # --- Фоновые задачи ---
    await backup_manager.start()

    yield

    # --- Остановка ---
    await backup_manager.stop()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Recipe Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ingress_middleware(request: Request, call_next):
    """HA ingress передаёт префикс пути в X-Ingress-Path.

    Устанавливаем root_path, чтобы FastAPI корректно строил URL-ы
    и совпадал с путями запросов.
    """
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if ingress_path:
        request.scope["root_path"] = ingress_path
    return await call_next(request)


# ---------------------------------------------------------------------------
# API-роутеры
# ---------------------------------------------------------------------------

app.include_router(api_router)


# ---------------------------------------------------------------------------
# Раздача статики
#
# Изначально использовался StaticFiles mount, но под HA ingress он некорректно
# работает с префиксами. Здесь — явный роут /static/{file_path} с ручным
# выбором MIME-типа. Это надёжнее и предсказуемее.
# ---------------------------------------------------------------------------

@app.get("/static/{file_path:path}", include_in_schema=False)
async def serve_static(file_path: str):
    from pathlib import Path
    from fastapi import HTTPException

    rel = Path(file_path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise HTTPException(400, "Invalid path")

    static_root = STATIC_DIR.resolve()
    full = (STATIC_DIR / rel).resolve()

    try:
        full.relative_to(static_root)
    except ValueError:
        raise HTTPException(400, "Invalid path")

    if not full.exists() or not full.is_file():
        raise HTTPException(404, f"Not found: {file_path}")

    media = _MIME.get(full.suffix.lower(), "application/octet-stream")
    return FileResponse(full, media_type=media)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    import aiofiles

    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse(
            "<h1>Recipe Manager</h1><p>index.html не найден в образе.</p>",
            status_code=500,
        )
    async with aiofiles.open(index_file, "r", encoding="utf-8") as f:
        return await f.read()