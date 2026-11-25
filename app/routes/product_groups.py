"""Группы логических продуктов и предложения объединения GTIN-вариантов."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from services.auth import get_current_user
from stores import ingredients_store

router = APIRouter(prefix="/api/product-groups", tags=["product-groups"])


def _require_admin(request: Request) -> None:
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")


@router.get("")
async def list_groups(request: Request):
    return {
        "groups": ingredients_store.get_groups(),
        "suggestions": ingredients_store.get_group_suggestions(status="pending"),
    }


@router.post("/suggest")
async def suggest_groups(request: Request):
    _require_admin(request)
    created = await ingredients_store.create_group_suggestions()
    return {
        "created": len(created),
        "suggestions": ingredients_store.get_group_suggestions(status="pending"),
    }


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(suggestion_id: str, request: Request):
    _require_admin(request)
    user = get_current_user(request) or {}
    group = await ingredients_store.approve_group_suggestion(
        suggestion_id, reviewed_by=user.get("id")
    )
    if group is None:
        raise HTTPException(404, "Suggestion not found or not pending")
    return {"group": group}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str, request: Request):
    _require_admin(request)
    user = get_current_user(request) or {}
    ok = await ingredients_store.reject_group_suggestion(
        suggestion_id, reviewed_by=user.get("id")
    )
    if not ok:
        raise HTTPException(404, "Suggestion not found or not pending")
    return {"rejected": True}


@router.post("/{group_id}/dissolve")
async def dissolve_group(group_id: str, request: Request):
    _require_admin(request)
    ok = await ingredients_store.dissolve_group(group_id)
    if not ok:
        raise HTTPException(404, "Group not found")
    return {"dissolved": True}
