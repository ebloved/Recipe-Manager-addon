"""Список покупок: CRUD + lookup по штрих-коду + добавление из рецепта."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from services.auth import get_current_user

from services.product_lookup import lookup_barcode
from stores import ingredients_store, recipe_store, shopping_store

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

    # B2: resolve product names for ingredients with product_id
    _products_by_id: dict[str, dict[str, Any]] = {}
    try:
        for _p in (getattr(ingredients_store, "products", None) or []):
            _pid = _p.get("id")
            if _pid:
                _products_by_id[_pid] = _p
    except Exception:  # noqa: BLE001
        _products_by_id = {}

    added = 0
    merged = 0
    for _, ing in selected:
        name = (ing.get("name") or "").strip()
        if not name:
            continue
        amount = ing.get("amount")
        if amount and multiplier != 1:
            amount = _scale_amount(amount, multiplier)
        product = _products_by_id.get(ing.get("product_id")) if ing.get("product_id") else None
        resolved_name = (product.get("name") or "").strip() if product else ""
        item_data: dict[str, Any] = {
            "name": resolved_name or name,
            "amount": amount,
            "unit": ing.get("unit"),
            "note": ing.get("notes"),
            "recipe_id": recipe_id,
            "recipe_name": recipe.get("name"),
            "source": "recipe",
            "product_id": ing.get("product_id") or None,
        }
        if product:
            item_data["brand"] = product.get("brand")
            item_data["barcode"] = product.get("barcode")
            item_data["image_url"] = product.get("image_url")
            item_data["category"] = product.get("category")
        _, was_merged = await shopping_store.add_or_merge(item_data, owner_id=get_current_user(request)['id'])
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


# ---------------------------------------------------------------------------
# Export for external MCP connector (VkusVill and others)
# ---------------------------------------------------------------------------

@router.get("/export-for-connector")
async def export_for_connector(request: Request, store_id: str = "vkusvill"):
    """Возвращает корзину в формате для внешнего MCP-коннектора."""
    from services.piece_weights import suggest_unit_and_quantity, get_default_weight, is_sold_by_piece
    from services.shopping_normalizer import normalize_for_connector
    from stores import ingredients_store

    user = get_current_user(request)
    uid = user["id"] if user else None
    user_weights = (user or {}).get("piece_weights", {}) or {}

    products_map = {}
    try:
        for pr in (getattr(ingredients_store, "products", None) or []):
            if pr.get("id"):
                products_map[pr["id"]] = pr
    except Exception:
        pass

    items_raw = shopping_store.get_all(owner_id=uid)
    items = []
    warnings = []

    for it in items_raw:
        if it.get("checked"):
            continue

        name = (it.get("name") or "").strip()
        if not name:
            continue

        piece_weight = user_weights.get(name)
        if not piece_weight:
            piece_weight = get_default_weight(name)

        suggestion = suggest_unit_and_quantity(it.get("amount"), it.get("unit"), name)
        if piece_weight and suggestion.get("piece_weight_g") is not None:
            try:
                q = float(it.get("amount"))
                suggestion["suggested_quantity"] = round(q * float(piece_weight), 1)
                suggestion["suggested_unit"] = "г"
                suggestion["piece_weight_g"] = float(piece_weight)
                suggestion["weight_unknown"] = False
            except (TypeError, ValueError):
                pass

        sku_hint = None
        product = products_map.get(it.get("product_id")) if it.get("product_id") else None
        if product:
            sh = {
                "barcode": product.get("barcode"),
                "brand": product.get("brand"),
                "name": product.get("name"),
            }
            sku_hint = {k: v for k, v in sh.items() if v}

        if suggestion.get("weight_unknown"):
            warnings.append(f"{name}: неизвестен вес 1 шт. Укажите в «Проверь себя».")

        su = (suggestion.get("suggested_unit") or "").lower()
        if suggestion.get("sold_as"):
            sold_as = suggestion["sold_as"]
        elif is_sold_by_piece(name):
            sold_as = "piece"
        elif su in ("г", "кг"):
            sold_as = "weight"
        elif su in ("мл", "л"):
            sold_as = "volume"
        else:
            sold_as = "piece"

        items.append({
            "id": it.get("id"),
            "canonical_name": name,
            "quantity_original": it.get("amount"),
            "unit_original": it.get("unit"),
            "suggested_quantity": suggestion.get("suggested_quantity"),
            "suggested_unit": suggestion.get("suggested_unit"),
            "sold_as": sold_as,
            "piece_weight_g": suggestion.get("piece_weight_g"),
            "weight_unknown": suggestion.get("weight_unknown", False),
            "notes": it.get("note") or "",
            "sku_hint": sku_hint,
            "product_id": it.get("product_id") or None,
            "recipes": [it.get("recipe_name")] if it.get("recipe_name") else [],
        })

    items_before_merge = len(items)
    merged_items = _merge_by_canonical(items)

    return {
        "schema_version": 1,
        "source": "recipe_manager",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "store": {
            "id": store_id,
            "name": "ВкусВилл" if store_id == "vkusvill" else store_id,
        },
        "items": merged_items,
        "warnings": warnings,
        "meta": {
            "total_items": len(merged_items),
            "items_before_merge": items_before_merge,
            "merged_groups": items_before_merge - len(merged_items),
            "items_linked_to_product": sum(1 for i in merged_items if i.get("product_id")),
            "merged_via_product_id": sum(1 for i in merged_items if i.get("merged_via") == "product_id"),
            "merged_via_canonical_name": sum(1 for i in merged_items if i.get("merged_via") == "canonical_name"),
            "sold_as_piece": sum(1 for i in merged_items if i.get("sold_as") == "piece"),
            "sold_as_weight": sum(1 for i in merged_items if i.get("sold_as") == "weight"),
            "sold_as_volume": sum(1 for i in merged_items if i.get("sold_as") == "volume"),
            "converted_from_pieces": sum(1 for i in merged_items if (i.get("unit_original") or "") in ("шт", "зубчик", "пучок") and i["suggested_unit"] == "г"),
            "unknown_weights": sum(1 for i in merged_items if i["weight_unknown"]),
        },
    }


def _merge_by_canonical(items: list[dict]) -> list[dict]:
    """Склеивает items в один продукт.

    Приоритет:
      1. product_id (если ингредиенты связаны с продуктом) — самый надежный сигнал.
      2. canonical_name + sold_as (нормализация имени).
    """
    from collections import defaultdict

    by_product: dict[str, list[dict]] = defaultdict(list)
    orphans: list[dict] = []
    for item in items:
        pid = item.get("product_id")
        if pid:
            by_product[pid].append(item)
        else:
            orphans.append(item)

    result: list[dict] = []

    for pid, group in by_product.items():
        units = {g.get("suggested_unit") for g in group}
        if len(units) > 1:
            for g in group:
                copy = dict(g)
                copy["merged_via"] = None
                result.append(copy)
            continue

        display_name = None
        for g in group:
            sh = g.get("sku_hint")
            if sh and sh.get("name"):
                display_name = sh["name"]
                break
        if not display_name:
            display_name = normalize_for_connector(group[0].get("canonical_name") or "")

        merged_via = "product_id" if len(group) > 1 else None
        merged = _do_merge(group, display_name, merged_via=merged_via)
        merged["product_id"] = pid
        result.append(merged)

    by_canon: dict[tuple, list[dict]] = defaultdict(list)
    for item in orphans:
        canon = normalize_for_connector(item.get("canonical_name") or "")
        sold_as = item.get("sold_as", "piece")
        by_canon[(canon, sold_as)].append(item)

    for (canon, sold_as), group in by_canon.items():
        merged_via = "canonical_name" if len(group) > 1 else None
        merged = _do_merge(group, canon, merged_via=merged_via)
        merged["product_id"] = None
        result.append(merged)

    return result


def _do_merge(group: list[dict], display_name: str, merged_via: str | None = None) -> dict:
    """Сливает группу items в один. Суммирует количество, объединяет notes/recipes."""
    if len(group) == 1:
        single = dict(group[0])
        single["canonical_name"] = display_name
        single["merged_via"] = merged_via
        return single

    total_qty = 0.0
    for g in group:
        try:
            total_qty += float(g.get("suggested_quantity") or 0)
        except (TypeError, ValueError):
            pass

    notes = [g.get("notes") for g in group if g.get("notes")]
    recipes: list[str] = []
    for g in group:
        recipes.extend(g.get("recipes") or [])
    seen = set()
    recipes = [r for r in recipes if not (r in seen or seen.add(r))]

    sku_hint = next((g.get("sku_hint") for g in group if g.get("sku_hint")), None)

    return {
        "id": group[0].get("id"),
        "canonical_name": display_name,
        "quantity_original": None,
        "unit_original": None,
        "suggested_quantity": round(total_qty, 2),
        "suggested_unit": group[0].get("suggested_unit"),
        "sold_as": group[0].get("sold_as", "piece"),
        "piece_weight_g": group[0].get("piece_weight_g") if group[0].get("sold_as") != "piece" else None,
        "weight_unknown": any(g.get("weight_unknown") for g in group),
        "notes": "; ".join(notes) if notes else "",
        "sku_hint": sku_hint,
        "recipes": recipes,
        "merged_from": [g.get("canonical_name") for g in group],
        "merged_via": merged_via,
    }
