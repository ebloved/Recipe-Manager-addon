"""Роуты Google OAuth."""
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, AUTH_MODE
from services.auth import create_session_token, users_store, SESSION_COOKIE

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
            real_ip = request.headers.get("CF-Connecting-IP") or request.client.host
            logger.warning(f"[AUTH] Access denied for {userinfo['email']} from {real_ip}")
            return RedirectResponse(url="/?error=access_denied")
        
        real_ip = request.headers.get("CF-Connecting-IP") or request.client.host
        logger.info(f"[AUTH] Login success: {user['email']} from {real_ip}")
        # Устанавливаем HttpOnly Cookie
        next_url = request.session.pop("next", "/")
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        response = RedirectResponse(url=next_url)
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
        secure_cookie = forwarded_proto == "https" or request.url.scheme == "https"
        response.set_cookie(
            key=SESSION_COOKIE,
            value=create_session_token(user["id"]),
            httponly=True,
            max_age=86400 * 7, # 7 дней
            samesite="lax",
            secure=secure_cookie,
        )
        return response
    except Exception as e:
        return RedirectResponse(url=f"/?error={str(e)}")

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("rm_session")
    return response
