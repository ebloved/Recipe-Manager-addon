"""Авторизация внешних API: персональный Bearer-токен или сессия."""
from __future__ import annotations

from fastapi import HTTPException, Request

from services.auth import get_current_user, users_store
from stores.api_tokens import api_tokens


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for", ""
    )
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or None
    return request.client.host[:64] if request.client else None


async def get_api_user(request: Request, *, scope: str | None = None) -> dict:
    """Возвращает пользователя по Bearer-токену или обычной сессии.

    Токены имеют вид `rm_...`; если Authorization есть, но токен неверный,
    запрос не откатывается на cookie — это явная ошибка авторизации.
    """
    auth = (request.headers.get("authorization") or "").strip()
    if auth:
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(401, "Invalid Authorization header")
        record = await api_tokens.verify(
            token.strip(),
            ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
        if not record:
            raise HTTPException(401, "Invalid or revoked API token")
        scopes = set(record.get("scopes") or [])
        if scope and scope not in scopes:
            raise HTTPException(403, f"Token has no '{scope}' scope")
        user = users_store.users.get(record["owner_id"])
        if not user:
            user = {
                "id": record["owner_id"],
                "name": "API",
                "role": "user",
            }
        else:
            user = dict(user)
        user["_api_scopes"] = sorted(scopes)
        user["_api_token_id"] = record.get("id")
        return user

    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Unauthorized")
    return user
