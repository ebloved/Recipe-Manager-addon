"""Список покупок: CRUD + lookup по штрих-коду + добавление из рецепта."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from services.product_lookup import lookup_barcode
from stores import recipe_store, shopping_store

router = APIRouter(prefix="/api/shopping", tags=["shopping"])


# --- CRUD -------------------------------------------------------------------

@router.get("")
async def list_items(only_active: bool = False):
    items = shopping_store.get_all(only_active=only_active)
    active = sum(1 for i in items if not i.get("checked"))
    return {
        "items": items,
        "count": len(items),
        "active": active,
    }


@router.post("")
async def add_item(payload: dict[str, Any] = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    item = await shopping_store.add(payload)
    return {"item": item}


@router.patch("/{item_id}")
async def update_item(item_id: str, patch: dict[str, Any] = Body(...)):
    item = await shopping_store.update(item_id, patch)
    if not item:
        raise HTTPException(404, "Item not found")
    return {"item": item}


@router.post("/{item_id}/toggle")
async def toggle_item(item_id: str):
    item = await shopping_store.toggle(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return {"item": item}


@router.delete("/checked")
async def clear_checked():
    removed = await shopping_store.clear_checked()
    return {"removed": removed}


@router.delete("/all")
async def clear_all():
    removed = await shopping_store.clear_all()
    return {"removed": removed}


@router.delete("/{item_id}")
async def delete_item(item_id: str):
    ok = await shopping_store.delete(item_id)
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
async def add_from_recipe(payload: dict[str, Any] = Body(...)):
    """Добавляет ингредиенты рецепта в список покупок.

    Payload:
        recipe_id: str
        ingredient_indices: list[int] | None
            Если не указан — берём все не-заголовки.
        multiplier: float = 1
    """
    recipe_id = payload.get("recipe_id")
    if not recipe_id:
        raise HTTPException(400, "'recipe_id' is required")

    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    multiplier = float(payload.get("multiplier") or 1)
    indices = payload.get("ingredient_indices")

    raw = recipe.get("ingredients") or []
    normalized = [
        ({"name": i, "amount": None, "unit": None, "notes": None}
         if isinstance(i, str) else i)
        for i in raw
    ]

    if indices is None:
        selected = [
            (idx, ing) for idx, ing in enumerate(normalized)
            if not ing.get("is_heading") and not (ing.get("name") or "").startswith("#")
        ]
    else:
        wanted = set(int(i) for i in indices)
        selected = [(idx, normalized[idx]) for idx in wanted if 0 <= idx < len(normalized)]

    added = 0
    merged = 0
    for _, ing in selected:
        name = (ing.get("name") or "").strip()
        if not name:
            continue
        amount = ing.get("amount")
        if amount and multiplier != 1:
            amount = _scale_amount(amount, multiplier)
        item_data = {
            "name": name,
            "amount": amount,
            "unit": ing.get("unit"),
            "note": ing.get("notes"),
            "recipe_id": recipe_id,
            "recipe_name": recipe.get("name"),
            "source": "recipe",
        }
        _, was_merged = await shopping_store.add_or_merge(item_data)
        if was_merged:
            merged += 1
        else:
            added += 1

    return {
        "added": added,
        "merged": merged,
        "total": added + merged,
    }


def _scale_amount(amount: Any, mult: float) -> Any:
    try:
        num = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        return amount
    result = num * mult
    if result.is_integer():
        return int(result)
    return round(result, 2)