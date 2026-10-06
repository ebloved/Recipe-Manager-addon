"""API профилей генерации рецептов.

CRUD, список, установка активного профиля. Профили используются
на этапе генерации рецептов (Итерация C) и фильтрации поиска.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from stores import gen_profiles_store

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# --- Список и чтение ------------------------------------------------------

@router.get("")
async def list_profiles(include_deleted: bool = Query(False)):
    items = gen_profiles_store.get_all(include_deleted=include_deleted)
    active = gen_profiles_store.get_active()
    return {
        "profiles": items,
        "count": len(items),
        "active_id": active["id"] if active else None,
    }


@router.get("/active")
async def get_active_profile():
    p = gen_profiles_store.get_active()
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
async def set_active_profile(payload: dict[str, Any] = Body(...)):
    """Устанавливает активный профиль.

    Payload: {"profile_id": "..."} или {"profile_id": null} для сброса.
    """
    profile_id = payload.get("profile_id") if isinstance(payload, dict) else None
    ok = await gen_profiles_store.set_active(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found or deleted")
    p = gen_profiles_store.get_active()
    return {"active_id": p["id"] if p else None, "profile": p}