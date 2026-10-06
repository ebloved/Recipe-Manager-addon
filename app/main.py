"""Recipe Manager — FastAPI backend для HA add-on."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config import (
    FEATURE_MATCHER,
    FEATURE_PRODUCTS,
    FEATURE_PROFILES,
    MATCHER_AUTO_THRESHOLD,
    MATCHER_CONFIRM_MODE,
    MATCHER_PROVIDER,
    MATCHER_SUGGEST_THRESHOLD,
)
from routes import api_router
from stores import (
    gen_profiles_store,
    ingredients_store,
    meal_plan_store,
    recipe_store,
    shopping_store,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Store'ы -----------------------------------------------------
    await recipe_store.load()
    await meal_plan_store.load()
    await shopping_store.load()

    if FEATURE_PRODUCTS:
        await ingredients_store.load()

    if FEATURE_PROFILES:
        await gen_profiles_store.load()

    # --- Матчинг ингредиентов ----------------------------------------
    if FEATURE_MATCHER:
        if not FEATURE_PRODUCTS:
            # Матчер без справочника продуктов бессмысленен.
            print(
                "[matcher] FEATURE_MATCHER=true, но FEATURE_PRODUCTS=false. "
                "Матчер отключён. Включите runtime_mode=standard или full."
            )
        else:
            # Реестр провайдеров инициализируется лениво — прогреваем сейчас,
            # чтобы ошибки конфигурации всплыли на старте, а не при первом
            # запросе пользователя.
            try:
                from services.matcher.providers import provider_registry
                provider_registry.initialize()
                snapshot = provider_registry.snapshot()
                names = [p["name"] for p in snapshot.get("providers", [])]
                print(
                    f"[matcher] provider={MATCHER_PROVIDER}, "
                    f"thresholds auto={MATCHER_AUTO_THRESHOLD} "
                    f"suggest={MATCHER_SUGGEST_THRESHOLD}, "
                    f"confirm={MATCHER_CONFIRM_MODE}, "
                    f"registered={names}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[matcher] initialization failed: {exc}")

    # --- Логи --------------------------------------------------------
    print(f"[recipes] loaded {len(recipe_store.recipes)} recipes")
    print(f"[meal-plan] loaded {len(meal_plan_store.entries)} entries")
    print(f"[shopping] loaded {len(shopping_store.items)} items")
    if FEATURE_PRODUCTS:
        print(f"[ingredients] loaded {len(ingredients_store.products)} products")
    if FEATURE_PROFILES:
        print(f"[gen_profiles] loaded {len(gen_profiles_store.profiles)} profiles")

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