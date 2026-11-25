"""Обратная связь от внешнего сервиса покупок."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from services.api_auth import get_api_user
from services.shopping_feedback import apply_purchase_feedback

router = APIRouter(prefix="/api/v1/shopping", tags=["shopping-feedback"])


@router.post("/purchased")
async def purchased(request: Request, payload: dict = Body(...)):
    user = await get_api_user(request, scope="export")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "items[] is required")
    if len(items) > 500:
        raise HTTPException(400, "Too many items (max 500)")
    mode = str(payload.get("mode") or "check").strip().lower()
    if mode not in ("check", "delete"):
        raise HTTPException(400, "mode must be 'check' or 'delete'")
    return await apply_purchase_feedback(user["id"], items, mode=mode)
