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


def _user(request: Request) -> dict[str, Any] | None:
    return get_current_user(request)


def _user_id(request: Request) -> str | None:
    user = _user(request)
    return user.get("id") if user else None


def _visible(profile: dict[str, Any], user_id: str | None) -> bool:
    owner = profile.get("owner_id")
    return not owner or owner == user_id


def _can_manage(profile: dict[str, Any], user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    owner = profile.get("owner_id")
    if owner:
        return owner == user.get("id")
    return user.get("role") == "admin"


def _profile_or_404(
    profile_id: str,
    user: dict[str, Any] | None,
    *,
    manage: bool = False,
) -> dict[str, Any]:
    profile = gen_profiles_store.get(profile_id)
    if not profile or not _visible(profile, (user or {}).get("id")):
        raise HTTPException(404, "Profile not found")
    if manage and not _can_manage(profile, user):
        raise HTTPException(403, "Нет прав на изменение профиля")
    return profile


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
            if (
                profile
                and not profile.get("deleted")
                and _visible(profile, user_id)
            ):
                return profile
            return None
    fallback = gen_profiles_store.get_active()
    if fallback and _visible(fallback, user_id):
        return fallback
    return None


# --- Список и чтение ------------------------------------------------------

@router.get("")
async def list_profiles(request: Request, include_deleted: bool = Query(False)):
    user_id = _user_id(request)
    user = _user(request)
    items = gen_profiles_store.get_all(
        include_deleted=include_deleted,
        owner_id=user_id,
    )
    items = [
        {**item, "can_edit": _can_manage(item, user)}
        for item in items
    ]
    active = await _active_profile(user_id)
    if active and not _visible(active, user_id):
        active = None
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
async def get_profile(profile_id: str, request: Request):
    p = _profile_or_404(profile_id, _user(request))
    return {"profile": p}


# --- CRUD -----------------------------------------------------------------

@router.post("")
async def create_profile(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    if not user:
        raise HTTPException(401, "Unauthorized")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    data = {
        **payload,
        "owner_id": user["id"],
        "source": payload.get("source") or "user",
    }
    profile = await gen_profiles_store.add(data)
    return {"profile": profile}


@router.patch("/{profile_id}")
async def update_profile(
    profile_id: str,
    request: Request,
    patch: dict[str, Any] = Body(...),
):
    user = _user(request)
    _profile_or_404(profile_id, user, manage=True)
    patch.pop("owner_id", None)
    patch.pop("source", None)
    p = await gen_profiles_store.update(profile_id, patch)
    if not p:
        raise HTTPException(404, "Profile not found")
    return {"profile": p}


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str, request: Request):
    user = _user(request)
    _profile_or_404(profile_id, user, manage=True)
    ok = await gen_profiles_store.soft_delete(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"deleted": True}


@router.post("/{profile_id}/restore")
async def restore_profile(profile_id: str, request: Request):
    user = _user(request)
    _profile_or_404(profile_id, user, manage=True)
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
        if (
            not profile
            or profile.get("deleted")
            or not _visible(profile, user_id)
        ):
            raise HTTPException(404, "Profile not found or deleted")
    await user_active_profiles.set(user_id, profile_id)
    p = await _active_profile(user_id)
    return {"active_id": p["id"] if p else None, "profile": p}