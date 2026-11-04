"""API профилей генерации рецептов.

CRUD, список, установка активного профиля. Профили используются
на этапе генерации рецептов (Итерация C) и фильтрации поиска.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from services.auth import get_current_user
from stores import gen_profiles_store
from stores.user_active_profiles import user_active_profiles

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _user_id(request: Request) -> str | None:
    user = get_current_user(request)
    return user.get("id") if user else None


async def _active_profile(user_id: str | None) -> dict[str, Any] | None:
    """Активный профиль пользователя; fallback — глобальный (legacy).

    Важно: NULL в user_active_profiles — это осознанный выбор «Без профиля»,
    а не отсутствие настройки. Поэтому сначала проверяем наличие записи.
    """
    if user_id:
        exists, pid = await user_active_profiles.get_with_presence(user_id)
        if exists:
            if not pid:
                return None
            profile = gen_profiles_store.get(pid)
            if profile and not profile.get("deleted"):
                return profile
            return None
    return gen_profiles_store.get_active()


# --- Список и чтение ------------------------------------------------------

@router.get("")
async def list_profiles(request: Request, include_deleted: bool = Query(False)):
    items = gen_profiles_store.get_all(include_deleted=include_deleted)
    active = await _active_profile(_user_id(request))
    return {
        "profiles": items,
        "count": len(items),
        "active_id": active["id"] if active else None,
    }


@router.get("/active")
async def get_active_profile(request: Request):
    p = await _active_profile(_user_id(request))
    return {"profile": p}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    p = gen_profiles_store.get(profile_id)
    if not p:
        raise HTTPException(404, "Profile not found")
    return {"profile": p}


# --- CRUD -----------------------------------------------------------------

@router.post("")
async def create_profile(payload: dict[str, Any] = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    profile = await gen_profiles_store.add(payload)
    return {"profile": profile}


@router.patch("/{profile_id}")
async def update_profile(profile_id: str, patch: dict[str, Any] = Body(...)):
    p = await gen_profiles_store.update(profile_id, patch)
    if not p:
        raise HTTPException(404, "Profile not found")
    return {"profile": p}


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    ok = await gen_profiles_store.soft_delete(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"deleted": True}


@router.post("/{profile_id}/restore")
async def restore_profile(profile_id: str):
    ok = await gen_profiles_store.restore(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"restored": True}


# --- Активный профиль -----------------------------------------------------

@router.post("/active")
async def set_active_profile(request: Request, payload: dict[str, Any] = Body(...)):
    """Устанавливает активный профиль текущего пользователя.

    Payload: {"profile_id": "..."} или {"profile_id": null} для сброса.
    """
    user_id = _user_id(request)
    if not user_id:
        raise HTTPException(401, "Unauthorized")
    profile_id = payload.get("profile_id") if isinstance(payload, dict) else None
    if profile_id:
        profile = gen_profiles_store.get(profile_id)
        if not profile or profile.get("deleted"):
            raise HTTPException(404, "Profile not found or deleted")
    await user_active_profiles.set(user_id, profile_id)
    p = await _active_profile(user_id)
    return {"active_id": p["id"] if p else None, "profile": p}