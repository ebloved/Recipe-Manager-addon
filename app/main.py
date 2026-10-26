"""Recipe Manager — FastAPI backend для HA add-on."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import (
    SECRET_KEY,
    AUTH_MODE,
    FEATURE_MATCHER,
    FEATURE_PRODUCTS,
    FEATURE_PROFILES,
    MATCHER_AUTO_THRESHOLD,
    MATCHER_CONFIRM_MODE,
    MATCHER_PROVIDER,
    MATCHER_SUGGEST_THRESHOLD,
)
from routes import api_router
from services.background_worker import active_time_worker
from stores import (
    gen_profiles_store,
    ingredients_store,
    meal_plan_store,
    recipe_store,
    shopping_store,
    suggestions_store,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Store'ы -----------------------------------------------------
    await recipe_store.load()
    await meal_plan_store.load()
    await shopping_store.load()
    await suggestions_store.load()
    from stores.jobs import jobs_store
    await jobs_store.load()
    from services.rate_limiter import rate_limiter
    await rate_limiter.load()
    from services.auth import users_store
    await users_store.load()
    from stores.settings import settings_store
    await settings_store.load()
    from config import DEPLOY_MODE
    if DEPLOY_MODE == "standalone":
        from services.telegram_service import telegram_service
        await telegram_service.reload(
            settings_store.get("telegram_bot_token"),
            settings_store.get("telegram_chat_id")
        )

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

                # B5: health-check всех провайдеров на старте
                try:
                    health_results = await provider_registry.health_all()
                    health_str = ", ".join(
                        f"{h.get('name', '?')}="
                        + ("ok" if h.get("available") else "unavailable")
                        + (f"({str(h.get('error', ''))[:40]})" if h.get("error") else "")
                        for h in health_results
                    )
                    print(f"[matcher] health: {health_str}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[matcher] health check failed: {exc}")
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

    import asyncio
    bg_task = asyncio.create_task(active_time_worker())
    
    # Безопасный запуск резумера
    try:
        from services.resumer import resume_interactions
        asyncio.create_task(resume_interactions())
    except Exception as exc:
        print(f"[resumer] Failed to start: {exc}")

    yield

    bg_task.cancel()


app = FastAPI(title="Recipe Manager", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
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