"""Список покупок: CRUD + lookup по штрих-коду + добавление из рецепта."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from services.auth import get_current_user

from services.product_lookup import lookup_barcode
from stores import recipe_store, shopping_store

router = APIRouter(prefix="/api/shopping", tags=["shopping"])


# --- CRUD -------------------------------------------------------------------

@router.get("")
async def list_items(request: Request, only_active: bool = False):
    user = get_current_user(request)
    items = shopping_store.get_all(owner_id=user['id'], only_active=only_active)
    active = sum(1 for i in items if not i.get("checked"))
    return {
        "items": items,
        "count": len(items),
        "active": active,
    }


@router.post("")
async def add_item(request: Request, payload: dict[str, Any] = Body(...)):
    user = get_current_user(request)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    item = await shopping_store.add(payload, owner_id=user['id'])
    return {"item": item}


@router.patch("/{item_id}")
async def update_item(item_id: str, request: Request, patch: dict[str, Any] = Body(...)):
    item = await shopping_store.update(item_id, owner_id=get_current_user(request)['id'], patch=patch)
    if not item:
        raise HTTPException(404, "Item not found")
    return {"item": item}


@router.post("/{item_id}/toggle")
async def toggle_item(item_id: str, request: Request):
    user = get_current_user(request)
    item = shopping_store.get(item_id)
    if not item or item.get('owner_id') != user['id']:
        raise HTTPException(404, "Item not found")
    updated = await shopping_store.update(
        item_id, owner_id=user['id'], patch={'checked': not item.get('checked', False)}
    )
    if not updated:
        raise HTTPException(404, "Item not found")
    return {"item": updated}


@router.delete("/checked")
async def clear_checked(request: Request):
    removed = await shopping_store.clear_checked(owner_id=get_current_user(request)['id'])
    return {"removed": removed}


@router.delete("/all")
async def clear_all(request: Request):
    removed = await shopping_store.clear_all(owner_id=get_current_user(request)['id'])
    return {"removed": removed}


@router.delete("/{item_id}")
async def delete_item(item_id: str, request: Request):
    ok = await shopping_store.delete(item_id, owner_id=get_current_user(request)['id'])
    if not ok:
        raise HTTPException(404, "Item not found")
    return {"deleted": True}


# --- Lookup -----------------------------------------------------------------

@router.post("/lookup")
async def lookup(payload: dict[str, Any] = Body(...)):
    """Ищет товар по штрих-коду. НЕ сохраняет — только возвращает данные."""
    barcode = (payload.get("barcode") or "").strip()
    if not barcode:
        raise HTTPException(400, "'barcode' is required")
    product = await lookup_barcode(barcode)
    return {"product": product}


# --- Add from recipe --------------------------------------------------------

@router.post("/from-recipe")
async def add_from_recipe(request: Request, payload: dict[str, Any] = Body(...)):
    """Добавляет ингредиенты рецепта в список покупок.

    Payload:
        recipe_id: str
        ingredient_indices: list[int] | None
            Если не указан — берём все не-заголовки.
        multiplier: float = 1
    """
    from services.shopping_from_recipe import add_recipe_ingredients_to_shopping

    recipe_id = payload.get("recipe_id")
    if not recipe_id:
        raise HTTPException(400, "'recipe_id' is required")

    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    return await add_recipe_ingredients_to_shopping(
        recipe,
        owner_id=get_current_user(request)["id"],
        multiplier=float(payload.get("multiplier") or 1),
        ingredient_indices=payload.get("ingredient_indices"),
    )


# ---------------------------------------------------------------------------
# Export for external MCP connector (VkusVill and others)
# ---------------------------------------------------------------------------

@router.get("/export-for-connector")
async def export_for_connector(request: Request, store_id: str = "vkusvill"):
    """Возвращает корзину в формате для внешнего MCP-коннектора."""
    from services.connector_export import build_connector_cart

    user = get_current_user(request)
    return build_connector_cart(user["id"], store_id, user)
