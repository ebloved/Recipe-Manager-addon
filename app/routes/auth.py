"""Роуты Google OAuth."""
import logging
import uuid
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, AUTH_MODE
from services.auth import (
    create_session_token,
    read_session_payload,
    read_session_token,
    users_store,
    SESSION_COOKIE,
)
from services import auth_sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@router.get("/login")
async def login(request: Request, next: str = "/"):
    if AUTH_MODE != "oauth":
        return {"status": "ok", "message": "Auth mode is not oauth"}
    
    # Динамически определяем redirect_uri на основе заголовков (для работы с несколькими доменами)
    # Caddy передает X-Forwarded-Host и X-Forwarded-Proto
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    request.session["next"] = safe_next

    host = request.headers.get("X-Forwarded-Host") or request.headers.get("host")
    scheme = request.headers.get("X-Forwarded-Proto") or request.url.scheme
    
    # Если есть порт в host (например, localhost:8099), оставляем его
    redirect_uri = f"{scheme}://{host}/api/auth/callback"
    
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/callback")
async def auth_callback(request: Request):
    userinfo = None
    try:
        token = await oauth.google.authorize_access_token(request)
        userinfo = token.get('userinfo')
        if not userinfo:
            raise HTTPException(400, "No userinfo")
        
        user = await users_store.get_or_create(
            google_id=userinfo["sub"],
            email=userinfo["email"],
            name=userinfo["name"],
            picture=userinfo.get("picture", "")
        )
        
        if not user:
            from services import audit

            real_ip = audit.client_ip(request)
            user_agent = (request.headers.get("user-agent") or "")[:300] or None
            logger.warning(f"[AUTH] Access denied for {userinfo['email']} from {real_ip}")
            try:
                await audit.log_event(
                    action="auth.login",
                    label="Отклонён вход",
                    actor_kind="anonymous",
                    actor_email=userinfo.get("email"),
                    actor_name=userinfo.get("name"),
                    status="denied",
                    error="Доступ запрещён: email нет в allowlist.",
                    error_code="auth_access_denied",
                    method="GET",
                    path=request.url.path,
                    http_status=403,
                    details={
                        "email": userinfo.get("email"),
                        "stage": "access_check",
                    },
                    ip=real_ip,
                    user_agent=user_agent,
                )
            except Exception:  # noqa: BLE001
                pass
            return RedirectResponse(url="/?error=access_denied")
        
        from services import audit

        real_ip = audit.client_ip(request)
        user_agent = request.headers.get("user-agent") or ""
        sid = uuid.uuid4().hex
        try:
            await auth_sessions.register_login(
                user["id"], sid, ip=real_ip, user_agent=user_agent[:300] or None
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AUTH] session register failed: %s", exc)
        logger.info(f"[AUTH] Login success: {user['email']} from {real_ip}")
        try:
            from services import audit

            actor = audit.resolve_actor(user.get("id"))
            await audit.log_event(
                action="auth.login",
                label="Вход в систему",
                actor_kind=actor["kind"],
                actor_id=actor["id"],
                actor_name=actor["name"],
                actor_email=actor["email"],
                actor_role=actor["role"],
                status="ok",
                method="GET",
                path=request.url.path,
                http_status=200,
                details={
                    "email": user.get("email"),
                    "provider": "google",
                    "session_id": sid,
                },
                ip=real_ip,
                user_agent=user_agent[:300] or None,
                correlation_id=sid,
            )
        except Exception:  # noqa: BLE001
            pass
        # Устанавливаем HttpOnly Cookie
        next_url = request.session.pop("next", "/")
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        response = RedirectResponse(url=next_url)
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
        secure_cookie = forwarded_proto == "https" or request.url.scheme == "https"
        response.set_cookie(
            key=SESSION_COOKIE,
            value=create_session_token(user["id"], sid),
            httponly=True,
            max_age=86400 * 7, # 7 дней
            samesite="lax",
            secure=secure_cookie,
        )
        return response
    except Exception as e:
        try:
            from services import audit

            await audit.log_event(
                action="auth.login",
                label="Неудачный вход",
                actor_kind="anonymous",
                actor_email=(userinfo or {}).get("email"),
                actor_name=(userinfo or {}).get("name"),
                status="error",
                error="Не удалось завершить OAuth-вход.",
                error_code="auth_oauth_failed",
                method="GET",
                path=request.url.path,
                http_status=400,
                details={
                    "stage": "callback",
                    "error_type": type(e).__name__,
                    "error": str(e)[:300],
                },
                ip=audit.client_ip(request),
                user_agent=(request.headers.get("user-agent") or "")[:300] or None,
            )
        except Exception:  # noqa: BLE001
            pass
        return RedirectResponse(url="/?error=auth_failed")

@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    payload = read_session_payload(token)
    uid = payload.get("uid") if payload else read_session_token(token)
    if uid:
        key = auth_sessions.session_key(payload, token)
        try:
            await auth_sessions.revoke_session(key)
        except Exception:  # noqa: BLE001
            pass
        try:
            from services import audit

            actor = audit.resolve_actor(uid)
            await audit.log_event(
                action="auth.logout",
                label="Выход из системы",
                actor_kind=actor["kind"],
                actor_id=actor["id"],
                actor_name=actor["name"],
                actor_email=actor["email"],
                actor_role=actor["role"],
                status="ok",
                details={"session_id": key, "reason": "logout"},
                ip=request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else None),
                user_agent=(request.headers.get("user-agent") or "")[:300] or None,
                correlation_id=key,
            )
        except Exception:  # noqa: BLE001
            pass
    response = RedirectResponse(url="/")
    response.delete_cookie("rm_session")
    return response
