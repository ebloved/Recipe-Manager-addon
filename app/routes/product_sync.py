"""API для внешнего обогащения справочника продуктов."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request

from services.api_auth import get_api_user
from services.product_sync import (
    NonFoodProductError,
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
    shopping_mode = str(payload.get("shopping_mode") or "check").strip().lower()
    if shopping_mode not in ("check", "delete"):
        raise HTTPException(400, "shopping_mode must be 'check' or 'delete'")
    return await record_observations(
        user["id"], items, shopping_mode=shopping_mode
    )


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
    group = ingredients_store.group_for_product(str(product.get("id")))
    return {
        "found": True,
        "product": {
            "product_id": product.get("id"),
            "name": product.get("name"),
            "barcode": product.get("barcode"),
            "brand": product.get("brand"),
            "category": product.get("category"),
            "default_unit": product.get("default_unit"),
            "group_id": product.get("group_id"),
            "identity_key": product.get("identity_key"),
            "group": group,
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
    try:
        product = await approve_suggestion(suggestion_id, admin_id=user["id"])
    except NonFoodProductError as exc:
        raise HTTPException(
            409, f"Non-food product ignored: {exc.reason}"
        ) from exc
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


# --- Логические продукты и GTIN-варианты ---------------------------------


@router.get("/groups")
async def groups(request: Request):
    """Группы логических продуктов с вариантами."""
    await get_api_user(request, scope="export")
    return {"groups": ingredients_store.get_groups()}


@router.get("/group-suggestions")
async def group_suggestions(request: Request, status: str = "pending"):
    """Предложения объединения вариантов в группу."""
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    return {
        "items": ingredients_store.get_group_suggestions(status=status or None)
    }


@router.post("/group-suggestions/scan")
async def scan_group_suggestions(request: Request):
    """Построить предложения групп по identity_key."""
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    created = await ingredients_store.create_group_suggestions()
    return {
        "created": len(created),
        "items": ingredients_store.get_group_suggestions(status="pending"),
    }


@router.post("/group-suggestions/{suggestion_id}/approve")
async def approve_group_suggestion(suggestion_id: str, request: Request):
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    group = await ingredients_store.approve_group_suggestion(
        suggestion_id, reviewed_by=user.get("id")
    )
    if group is None:
        raise HTTPException(404, "Group suggestion not found or already reviewed")
    return {"status": "approved", "group": group}


@router.post("/group-suggestions/{suggestion_id}/reject")
async def reject_group_suggestion(suggestion_id: str, request: Request):
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    ok = await ingredients_store.reject_group_suggestion(
        suggestion_id, reviewed_by=user.get("id")
    )
    if not ok:
        raise HTTPException(404, "Group suggestion not found or already reviewed")
    return {"status": "rejected"}


@router.post("/groups/{group_id}/dissolve")
async def dissolve_group(group_id: str, request: Request):
    user = await get_api_user(request, scope="products:write")
    _admin(user)
    ok = await ingredients_store.dissolve_group(group_id)
    if not ok:
        raise HTTPException(404, "Group not found")
    return {"status": "dissolved"}
