"""Публичные ссылки и форк рецептов.

Правила:
  - создать/отозвать ссылку может только владелец рецепта (или админ);
  - публичный GET отдаёт только whitelisted-поля;
  - форк создаётся текущему пользователю, а не владельцу оригинала;
  - публичный GET ограничен простым rate-limit по IP.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services.auth import get_current_user
from services.share_view import public_recipe
from stores import recipe_store

router = APIRouter(prefix="/api/sharing", tags=["sharing"])

# token → время запросов (не больше 60 в минуту с одного IP)
_RATE_WINDOW = 60.0
_RATE_LIMIT = 60
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_ok(request: Request) -> None:
    ip = _client_ip(request)
    now = time.time()
    bucket = _hits[ip]
    while bucket and now - bucket[0] > _RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    bucket.append(now)


def _user_or_401(request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    if not user or not user.get("id"):
        raise HTTPException(401, "Unauthorized")
    return user


def _can_manage(user: dict[str, Any], recipe: dict[str, Any]) -> bool:
    if recipe.get("personal_of"):
        return bool(user and recipe.get("owner_id") == user.get("id"))
    if user.get("role") == "admin":
        return True
    owner = recipe.get("owner_id")
    return bool(owner) and owner == user.get("id")


@router.post("/{recipe_id}/share")
async def create_share_link(recipe_id: str, request: Request):
    user = _user_or_401(request)
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    if not _can_manage(user, recipe):
        raise HTTPException(403, "Можно делиться только своими рецептами")

    token = recipe.get("share_token")
    created = not token
    if created:
        # Один токен на рецепт: повторный запрос не создаёт новую ссылку.
        token = uuid.uuid4().hex
        while recipe_store.get_by_share_token(token):
            token = uuid.uuid4().hex
        await recipe_store.update(recipe_id, {
            "share_token": token,
            "visibility": "unlisted",
        })
    # В журнал пишем отдельно создание новой ссылки и повторную выдачу
    # уже существующей — иначе кажется, что рецепт опубликовали снова.
    request.state.audit_action = "share.create" if created else "share.reuse"
    request.state.audit_action_label = (
        "Создание ссылки на рецепт" if created else "Повторная выдача ссылки"
    )
    request.state.audit_details = {"token_created": created}
    return {"token": token}


@router.delete("/{recipe_id}/share")
async def revoke_share_link(recipe_id: str, request: Request):
    user = _user_or_401(request)
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    if not _can_manage(user, recipe):
        raise HTTPException(403, "Можно отзывать только свои ссылки")

    await recipe_store.update(recipe_id, {
        "share_token": None,
        "visibility": "private",
    })
    return {"status": "revoked"}


@router.get("/{token}")
async def get_shared_recipe(token: str, request: Request):
    _rate_ok(request)
    recipe = recipe_store.get_by_share_token(token)
    if not recipe:
        raise HTTPException(404, "Shared recipe not found or link revoked")
    return {"recipe": public_recipe(recipe)}


@router.post("/{token}/fork")
async def fork_shared_recipe(token: str, request: Request):
    user = _user_or_401(request)
    _rate_ok(request)
    original = recipe_store.get_by_share_token(token)
    if not original:
        raise HTTPException(404, "Shared recipe not found")

    new_recipe = {k: v for k, v in original.items() if k not in (
        "id", "created_at", "updated_at", "share_token", "visibility",
        "normalization_hash", "normalization_status", "normalization_error",
        "normalization_issues", "normalized_at",
    )}
    new_recipe["name"] = f"{original.get('name')} (копия)"
    new_recipe["owner_id"] = user["id"]
    new_recipe["owner_name"] = user.get("name") or user.get("email")
    new_recipe["visibility"] = "private"

    created = await recipe_store.add(new_recipe)
    return {"recipe": public_recipe(created)}
