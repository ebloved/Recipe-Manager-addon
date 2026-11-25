"""API для внешнего обогащения справочника продуктов."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request

from services.api_auth import get_api_user
from services.product_sync import (
    approve_suggestion,
    list_suggestions,
    normalize_barcode,
    record_observations,
    reject_suggestion,
)
from stores import ingredients_store

router = APIRouter(prefix="/api/v1/products", tags=["product-sync"])


def _admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")


@router.post("/observations")
async def observations(request: Request, payload: dict = Body(...)):
    user = await get_api_user(request, scope="products:write")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "items[] is required")
    if len(items) > 500:
        raise HTTPException(400, "Too many items (max 500)")
    return await record_observations(user["id"], items)


@router.get("/lookup")
async def lookup(
    request: Request,
    barcode: str | None = Query(None),
    name: str | None = Query(None),
):
    user = await get_api_user(request, scope="export")
    product = None
    normalized = normalize_barcode(barcode)
    if normalized:
        product = ingredients_store.find_by_barcode(normalized)
    if product is None and name:
        product = ingredients_store.find_by_name(name)
    if not product:
        return {"found": False, "product": None}
    return {
        "found": True,
        "product": {
            "product_id": product.get("id"),
            "name": product.get("name"),
            "barcode": product.get("barcode"),
            "brand": product.get("brand"),
            "category": product.get("category"),
            "default_unit": product.get("default_unit"),
        },
    }


@router.get("/suggestions")
async def suggestions(
    request: Request,
    status: str = "pending",
):
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    return {"items": await list_suggestions(status or None)}


@router.post("/suggestions/{suggestion_id}/approve")
async def approve(suggestion_id: str, request: Request):
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    product = await approve_suggestion(suggestion_id, admin_id=user["id"])
    if product is None:
        raise HTTPException(404, "Suggestion not found or already reviewed")
    return {"status": "approved", "product": product}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject(suggestion_id: str, request: Request):
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    ok = await reject_suggestion(suggestion_id, admin_id=user["id"])
    if not ok:
        raise HTTPException(404, "Suggestion not found or already reviewed")
    return {"status": "rejected"}
