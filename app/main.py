"""Recipe Manager — FastAPI backend для HA add-on."""
from __future__ import annotations

import time

import httpx
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import (
    TEST_MODE,
    TEST_TOKEN,
    SECRET_KEY,
    AUTH_MODE,
    CORS_ORIGINS,
    REMOTE_MODE,
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
    meal_plan_drafts_store,
    progress_store,
    recipe_store,
    shopping_store,
    suggestions_store,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- SQLite (список покупок, магазины, кеш SKU) -------------------
    from db import init_db
    await init_db()

    from services import audit
    await audit.mark_stale_running()

    # --- Store'ы -----------------------------------------------------
    await recipe_store.load()
    await meal_plan_store.load()
    await meal_plan_drafts_store.load()
    await progress_store.load()
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

    from services.recipe_normalizer_worker import recipe_normalizer_worker
    normalizer_task = asyncio.create_task(recipe_normalizer_worker())

    from services.semantic_enricher_worker import semantic_enricher_worker
    enricher_task = asyncio.create_task(semantic_enricher_worker())

    from services.step_audio_worker import step_audio_worker
    tts_task = asyncio.create_task(step_audio_worker())

    from services.audit import audit_cleanup_worker
    audit_task = asyncio.create_task(audit_cleanup_worker())

    from services.backup import backup_manager
    await backup_manager.start()

    remote_task = None
    if REMOTE_MODE:
        async def _remote_sync_loop():
            from services import audit, remote_cache, remote_client

            failing = False
            while True:
                try:
                    if remote_client.get_token() and remote_client.get_server_url():
                        await remote_cache.sync_all()
                    if failing:
                        failing = False
                        await audit.log_event(
                            action="automation.remote_sync",
                            label="Синхронизация с сервером",
                            status="ok",
                            details={"recovered": True},
                        )
                except Exception as exc:  # noqa: BLE001
                    print(f"[remote] sync failed: {exc}")
                    if not failing:
                        failing = True
                        try:
                            await audit.log_event(
                                action="automation.remote_sync",
                                label="Синхронизация с сервером",
                                status="error",
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        except Exception:  # noqa: BLE001
                            pass
                await asyncio.sleep(60)

        remote_task = asyncio.create_task(_remote_sync_loop())

    # Безопасный запуск резумера
    try:
        from services.resumer import resume_interactions
        asyncio.create_task(resume_interactions())
    except Exception as exc:
        print(f"[resumer] Failed to start: {exc}")

    yield

    bg_task.cancel()
    normalizer_task.cancel()
    enricher_task.cancel()
    tts_task.cancel()
    audit_task.cancel()
    if remote_task:
        remote_task.cancel()
    try:
        await backup_manager.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[backup] stop failed: {exc}")


app = FastAPI(title="Recipe Manager", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def ingress_middleware(request: Request, call_next):
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if ingress_path:
        request.scope["root_path"] = ingress_path
    return await call_next(request)


# --- Auth guard -------------------------------------------------------------
# OAuth-режим: все /api/* требуют подписанную сессию, кроме явного allowlist.
# HA-режим: доступ уже ограничен ingress'ом.
_PUBLIC_API = {
    "/api/health",
    "/api/me",
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/logout",
    "/api/v1/health",
    "/api/v1/auth/device/init",
    "/api/v1/auth/device/poll",
}

_AUTH_HITS: dict[str, deque[float]] = defaultdict(deque)
_AUTH_FAIL_LAST: dict[str, float] = {}
_AUTH_WINDOW = 60.0
_AUTH_LIMIT = 10


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _auth_rate_ok(request: Request) -> bool:
    if TEST_MODE:
        return True
    ip = _client_ip(request)
    now = time.monotonic()
    bucket = _AUTH_HITS[ip]
    while bucket and now - bucket[0] > _AUTH_WINDOW:
        bucket.popleft()
    if len(bucket) >= _AUTH_LIMIT:
        return False
    bucket.append(now)
    return True


@app.middleware("http")
async def audit_log_middleware(request: Request, call_next):
    """Пишет в журнал изменения API: кто, что, статус и ошибку."""
    from services import audit

    event_id = await audit.start_request_event(request)
    if not event_id:
        return await call_next(request)
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        state_error = getattr(request.state, "audit_error", None) or {}
        state_details = dict(getattr(request.state, "audit_details", None) or {})
        state_details.update(state_error.get("details") or {})
        await audit.finish_event(
            event_id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            error_code=state_error.get("code") or "exception",
            error_provider=state_error.get("provider"),
            error_model=state_error.get("model"),
            details_extra=state_details or None,
            action=getattr(request.state, "audit_action", None),
            action_label=getattr(request.state, "audit_action_label", None),
        )
        raise

    state_error = getattr(request.state, "audit_error", None) or {}
    state_details = dict(getattr(request.state, "audit_details", None) or {})
    state_details.update(state_error.get("details") or {})
    state_action = getattr(request.state, "audit_action", None)
    state_action_label = getattr(request.state, "audit_action_label", None)

    if response.status_code >= 400:
        # BaseHTTPMiddleware отдаёт streaming-response, поэтому тело ошибки
        # нужно прочитать и вернуть клиенту заново.
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
        body = b"".join(chunks)
        await audit.finish_event(
            event_id,
            status=audit.response_status(response),
            http_status=response.status_code,
            error=audit.error_from_body(body),
            error_code=state_error.get("code") or audit.error_code_for_status(
                response.status_code
            ),
            error_provider=state_error.get("provider"),
            error_model=state_error.get("model"),
            details_extra=state_details or None,
            action=state_action,
            action_label=state_action_label,
        )
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in ("content-length", "content-encoding")
        }
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    await audit.finish_from_response(
        event_id,
        response,
        audit_error=state_error,
        details_extra=state_details or None,
        action=state_action,
        action_label=state_action_label,
    )
    return response


def _auth_failure_log_allowed(key: str, interval: float) -> bool:
    now = time.monotonic()
    last = _AUTH_FAIL_LAST.get(key)
    if last is not None and now - last < interval:
        return False
    if len(_AUTH_FAIL_LAST) > 2000:
        _AUTH_FAIL_LAST.clear()
    _AUTH_FAIL_LAST[key] = now
    return True


async def _log_auth_failure(
    request: Request,
    *,
    action: str,
    label: str,
    error: str,
    error_code: str,
    http_status: int,
    details: dict | None = None,
) -> None:
    from services import audit

    ip = audit.client_ip(request)
    path = request.url.path
    # Не забиваем журнал одинаковыми 401 с одного IP каждую секунду.
    interval = 5.0 if path.startswith("/api/auth/") else 30.0
    key = f"{ip or '-'}:{path}:{error_code}"
    if not _auth_failure_log_allowed(key, interval):
        return
    auth_header = (request.headers.get("authorization") or "").lower()
    data = {
        "path": path,
        "method": request.method.upper(),
        "session_present": bool(request.cookies.get("rm_session")),
        "bearer_present": auth_header.startswith("bearer "),
    }
    if details:
        data.update(details)
    try:
        await audit.log_event(
            action=action,
            label=label,
            actor_kind="anonymous",
            status="denied",
            error=error,
            error_code=error_code,
            method=request.method,
            path=path,
            http_status=http_status,
            details=data,
            ip=ip,
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[auth-audit] failed: {type(exc).__name__}: {exc}")


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    if AUTH_MODE != "oauth":
        return await call_next(request)

    path = request.scope.get("path") or request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)

    if (path.startswith("/api/auth/") or path.startswith("/api/v1/auth/device/")) and not _auth_rate_ok(request):
        await _log_auth_failure(
            request,
            action="auth.rate_limit",
            label="Превышен лимит попыток входа",
            error="Слишком много попыток авторизации.",
            error_code="auth_rate_limit",
            http_status=429,
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Слишком много попыток авторизации. Попробуйте позже."},
        )

    if path in _PUBLIC_API or path.startswith("/api/sharing/"):
        return await call_next(request)

    from services.auth import get_current_user
    if not get_current_user(request):
        has_cookie = bool(request.cookies.get("rm_session"))
        has_bearer = (request.headers.get("authorization") or "").lower().startswith("bearer ")
        if has_cookie or has_bearer:
            reason = "Недействительная или истёкшая сессия."
            code = "auth_invalid_session"
        else:
            reason = "Запрос без авторизации."
            code = "auth_required"
        await _log_auth_failure(
            request,
            action="auth.denied",
            label="Отклонён доступ без авторизации",
            error=reason,
            error_code=code,
            http_status=401,
        )
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    # Bearer device-token не отправляется браузером автоматически,
    # поэтому CSRF-проверка Origin к нему не применима. Это нужно BFF:
    # он проксирует запросы из HA ingress со своим Origin.
    if getattr(request.state, "device_user", None):
        return await call_next(request)

    # Базовая CSRF-защита для cookie-сессии: браузер присылает Origin на
    # state-changing same-origin запросы. CLI/API без Origin не ломаем.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin:
            expected = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
            if origin != expected:
                await _log_auth_failure(
                    request,
                    action="auth.csrf",
                    label="Отклонена cross-origin попытка",
                    error="Cross-origin state change is not allowed.",
                    error_code="auth_csrf",
                    http_status=403,
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin state change is not allowed"},
                )

    return await call_next(request)


@app.middleware("http")
async def device_auth_middleware(request: Request, call_next):
    if AUTH_MODE == "oauth":
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            from services.device_auth import authenticate_device

            user = await authenticate_device(request)
            if user:
                request.state.device_user = user
    return await call_next(request)


if TEST_MODE:
    print("[TEST_MODE] WARNING: auth bypass from 127.0.0.1/::1 enabled. Never use in prod!")

    @app.middleware("http")
    async def test_mode_middleware(request: Request, call_next):
        client_host = request.client.host if request.client else ""
        token = request.headers.get("X-Test-Token", "")
        if (
            TEST_TOKEN
            and token == TEST_TOKEN
            and client_host in ("127.0.0.1", "::1")
        ):
            request.state.test_mode_user = {
                "id": "smoke-test-user",
                "role": "admin",
                "name": "Smoke Test",
                "source": "test",
            }
        return await call_next(request)


@app.middleware("http")
async def remote_proxy_middleware(request: Request, call_next):
    """BFF: в remote-режиме проксируем API на сервер с device-token."""
    if not REMOTE_MODE:
        return await call_next(request)

    path = request.scope.get("path") or request.url.path
    if path.startswith("/api/remote/") or path == "/api/health":
        return await call_next(request)
    if not (
        path.startswith("/api/")
        or path.startswith("/files/")
        or path.startswith("/media/")
    ):
        return await call_next(request)

    from services import remote_client

    token = remote_client.get_token()
    server = remote_client.get_server_url()
    if not token or not server:
        return await call_next(request)

    body = await request.body()
    # Origin/Referer относятся к браузерной cookie-сессии HA, а не к
    # серверу. Наружу уходит Bearer device-token, поэтому не пересылаем
    # их — иначе сервер отвергнет state-changing запрос как cross-origin.
    skip = {
        "host", "cookie", "content-length", "authorization", "connection",
        "origin", "referer",
    }
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}
    headers["Authorization"] = f"Bearer {token}"
    url = server + path
    try:
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=False) as client:
            resp = await client.request(
                request.method,
                url,
                params=request.query_params,
                content=body,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        from services import remote_offline

        offline = await remote_offline.handle(request, body)
        if offline is not None:
            return offline
        return JSONResponse(
            status_code=502,
            content={"detail": f"remote server unavailable: {exc}"},
        )

    if path == "/api/me" and resp.status_code == 200:
        try:
            import json as _json
            from services import remote_cache

            remote_cache.cache_me(_json.loads(resp.content.decode("utf-8")))
        except Exception:  # noqa: BLE001
            pass

    keep = {"content-type", "content-disposition", "cache-control", "etag", "last-modified"}
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() in keep}
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=out_headers,
    )


app.include_router(api_router)