"""API «Готовлю сейчас»."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from services import cooking

router = APIRouter(prefix="/api/cooking", tags=["cooking"])


def _user(request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    if not user or not user.get("id"):
        raise HTTPException(401, "Unauthorized")
    return user


@router.get("/current")
async def get_current(request: Request):
    user = _user(request)
    return await cooking.get_current(user["id"])


@router.post("/current")
async def set_current(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    try:
        return await cooking.set_current(
            user["id"],
            main_recipe_id=(payload.get("main_recipe_id") or None),
            side_recipe_id=(payload.get("side_recipe_id") or None),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/current/check")
async def check_ingredients(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    checked = payload.get("checked_ingredients")
    if not isinstance(checked, list):
        raise HTTPException(400, "checked_ingredients must be a list")
    try:
        return await cooking.update_checked(user["id"], [str(x) for x in checked])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/current")
async def clear_current(request: Request):
    user = _user(request)
    await cooking.clear(user["id"])
    return {"active": False}


@router.post("/current/send-to-plan")
async def send_to_plan(request: Request, payload: dict[str, Any] = Body(default={})):
    user = _user(request)
    try:
        return await cooking.send_to_plan(
            user["id"], meal_type=payload.get("meal_type")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/current/send-to-shopping")
async def send_to_shopping(request: Request):
    user = _user(request)
    try:
        return await cooking.send_to_shopping(user["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
