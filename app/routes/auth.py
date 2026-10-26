"""Роуты Google OAuth."""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, AUTH_MODE
from services.auth import users_store

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
async def login(request: Request):
    if AUTH_MODE != "oauth":
        return {"status": "ok", "message": "Auth mode is not oauth"}
    # Передаем redirect_uri явно, чтобы совпадало с настройками в Google Console
    return await oauth.google.authorize_redirect(request, GOOGLE_REDIRECT_URI)

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
            return RedirectResponse(url="/?error=access_denied")
        
        # Устанавливаем HttpOnly Cookie
        response = RedirectResponse(url="/")
        response.set_cookie(
            key="rm_session",
            value=user["id"],
            httponly=True,
            max_age=86400 * 7, # 7 дней
            samesite="lax",
            secure=False # В продакшене поставить True (HTTPS)
        )
        return response
    except Exception as e:
        return RedirectResponse(url=f"/?error={str(e)}")

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("rm_session")
    return response
