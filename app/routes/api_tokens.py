"""Управление персональными API-токенами (только из браузерной сессии)."""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from stores.api_tokens import api_tokens, normalize_events, normalize_scopes

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


@router.patch("/{token_id}")
async def update_webhook(token_id: str, request: Request, payload: dict = Body(...)):
    user = _user_or_401(request)
    callback_url = str(payload.get("callback_url") or "").strip()[:1000]
    if callback_url:
        parsed = urlparse(callback_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(400, "callback_url must be http(s) URL")
    events = normalize_events(payload.get("callback_events"))
    item = await api_tokens.set_webhook(
        user["id"],
        token_id,
        callback_url=callback_url,
        callback_events=events,
    )
    if item is None:
        raise HTTPException(404, "Token not found")
    return {"item": item}


@router.post("/{token_id}/test-webhook")
async def test_webhook(token_id: str, request: Request):
    user = _user_or_401(request)
    from services.webhooks import webhook_manager

    result = await webhook_manager.send_test(user["id"], token_id)
    if result is None:
        raise HTTPException(404, "Token not found or callback_url is empty")
    return result


@router.delete("/{token_id}")
async def revoke_token(token_id: str, request: Request):
    user = _user_or_401(request)
    ok = await api_tokens.revoke(user["id"], token_id)
    if not ok:
        raise HTTPException(404, "Token not found")
    return {"revoked": True}
