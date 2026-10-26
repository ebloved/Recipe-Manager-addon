from fastapi import APIRouter, Request
from config import AUTH_MODE
from services.auth import users_store

router = APIRouter(prefix="/api/me", tags=["me"])

@router.get("")
async def get_me(request: Request):
    # 1. Если режим OAuth — проверяем куку
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
        
    # 2. Если режим HA — читаем заголовки (как раньше)
    name = request.headers.get("X-Remote-User-Display-Name") or request.headers.get("X-Remote-User-Name")
    uid = request.headers.get("X-Remote-User-Id")
    if name:
        return {"authenticated": True, "name": name, "id": uid, "source": "ha"}
    
    return {"authenticated": True, "name": "Семья", "id": "local", "source": "direct"}
