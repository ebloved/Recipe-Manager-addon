"""Управление персональными API-токенами (только из браузерной сессии)."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from stores.api_tokens import api_tokens, normalize_scopes

router = APIRouter(prefix="/api/me/api-tokens", tags=["api-tokens"])


def _user_or_401(request: Request) -> dict:
    user = get_current_user(request)
    if not user or not user.get("id"):
        raise HTTPException(401, "Unauthorized")
    return user


@router.get("")
async def list_tokens(request: Request):
    user = _user_or_401(request)
    items = await api_tokens.list(user["id"])
    return {"items": items}


@router.post("")
async def create_token(request: Request, payload: dict = Body(...)):
    user = _user_or_401(request)
    name = str(payload.get("name") or "API token").strip()[:200] or "API token"
    scopes = normalize_scopes(payload.get("scopes"))
    token, item = await api_tokens.create(
        user["id"],
        name=name,
        scopes=scopes,
    )
    return {
        "token": token,
        "item": item,
        "warning": "Токен показывается один раз. Сохраните его сейчас.",
    }


@router.delete("/{token_id}")
async def revoke_token(token_id: str, request: Request):
    user = _user_or_401(request)
    ok = await api_tokens.revoke(user["id"], token_id)
    if not ok:
        raise HTTPException(404, "Token not found")
    return {"revoked": True}
