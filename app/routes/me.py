"""Эндпоинт текущего пользователя."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/me", tags=["me"])

@router.get("")
async def get_me(request: Request):
    """Возвращает инфу о том, кто сейчас в системе.
    Читает заголовки HA Ingress. Если их нет (прямой доступ) — 'Family'.
    В standalone здесь будет OAuth-сессия.
    """
    name = request.headers.get("X-Remote-User-Display-Name") or request.headers.get("X-Remote-User-Name")
    uid = request.headers.get("X-Remote-User-Id")
    if name:
        return {"name": name, "id": uid, "source": "ha"}
    return {"name": "Семья", "id": "local", "source": "direct"}
