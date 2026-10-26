from fastapi import APIRouter, Request, HTTPException, Body
from config import AUTH_MODE
from services.auth import users_store
from pydantic import BaseModel

router = APIRouter(prefix="/api/me", tags=["me"])

class LLMConfigPayload(BaseModel):
    gemini_api_key: str | None = None
    external_llm_url: str | None = None
    external_llm_key: str | None = None
    external_llm_model: str | None = None
    preferred_provider: str | None = "auto"

@router.get("")
async def get_me(request: Request):
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            return {"authenticated": False}
        
        user = users_store.users[session_id]
        return {
            "authenticated": True,
            "name": user["name"],
            "email": user["email"],
            "picture": user.get("picture"),
            "id": user["id"],
            "role": user.get("role"),
            "source": "oauth"
        }
        
    name = request.headers.get("X-Remote-User-Display-Name") or request.headers.get("X-Remote-User-Name")
    uid = request.headers.get("X-Remote-User-Id")
    if name:
        return {"authenticated": True, "name": name, "id": uid, "source": "ha"}
    
    return {"authenticated": True, "name": "Семья", "id": "local", "source": "direct"}

@router.get("/llm")
async def get_llm_config(request: Request):
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
    session_id = request.cookies.get("rm_session")
    if not session_id or session_id not in users_store.users:
        raise HTTPException(401, "Unauthorized")
    
    conf = users_store.get_llm_config(session_id)
    return {
        "gemini_api_key_set": bool(conf.get("gemini_api_key")),
        "external_llm_url": conf.get("external_llm_url") or "",
        "external_llm_key_set": bool(conf.get("external_llm_key")),
        "external_llm_model": conf.get("external_llm_model") or "",
    }

@router.post("/llm/validate")
async def validate_llm_key(request: Request, payload: dict = Body(...)):
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
        
    key = payload.get("key", "").strip()
    if not key:
        raise HTTPException(400, "Ключ не может быть пустым")
        
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
            if resp.status_code != 200:
                try:
                    err_data = resp.json()
                    msg = err_data.get("error", {}).get("message", "Неверный ключ")
                except Exception:
                    msg = f"HTTP {resp.status_code}"
                raise HTTPException(400, msg)
        return {"status": "ok"}
    except httpx.RequestError as e:
        raise HTTPException(503, f"Ошибка сети: {e}")

@router.post("/llm")
async def update_llm_config(request: Request, payload: LLMConfigPayload):
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            raise HTTPException(401, "Unauthorized")
        
        await users_store.save_llm_config(session_id, payload.dict())
        return {"status": "ok"}
    
    raise HTTPException(400, "Not available in HA mode")
