"""Recipe Manager — FastAPI backend для HA add-on.

Здесь только:
- создание app
- lifespan (загрузка store'ов)
- middleware (CORS + ingress)
- include_router
- mount static

Вся логика — в модулях routes/, services/, stores/.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import STATIC_DIR
from routes import api_router
from stores import meal_plan_store, recipe_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    await recipe_store.load()
    await meal_plan_store.load()
    print(f"[recipes] loaded {len(recipe_store.recipes)} recipes")
    print(f"[meal-plan] loaded {len(meal_plan_store.entries)} entries")
    yield


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
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if ingress_path:
        request.scope["root_path"] = ingress_path
    return await call_next(request)


app.include_router(api_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")