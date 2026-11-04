"""Сборка корзины для магазинов из списка покупок.

Вынесено из routes/shopping.py, чтобы использовать и в legacy-экспорте,
и в новом модуле магазинов.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from services.piece_weights import (
    get_default_weight,
    is_sold_by_piece,
    suggest_unit_and_quantity,
)
from services.recipe_standard import canonical_name
from services.shopping_normalizer import normalize_for_connector
from stores import ingredients_store, shopping_store


def build_connector_cart(
    owner_id: str,
    store_id: str = "vkusvill",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Возвращает v1-совместимую корзину для коннектора."""
    user = user or {}
    user_weights = user.get("piece_weights", {}) or {}

    products_map: dict[Any, dict[str, Any]] = {}
    try:
        raw_products = getattr(ingredients_store, "products", None) or {}
        products = raw_products.values() if isinstance(raw_products, dict) else raw_products
        for product in products:
            if isinstance(product, dict) and product.get("id"):
                products_map[product["id"]] = product
    except Exception:  # noqa: BLE001
        pass

    items_raw = shopping_store.get_all(owner_id=owner_id)
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    for item in items_raw:
        if item.get("checked"):
            continue

        name = (item.get("name") or "").strip()
        if not name:
            continue

        piece_weight = user_weights.get(name)
        if not piece_weight:
            piece_weight = get_default_weight(name)

        suggestion = suggest_unit_and_quantity(item.get("amount"), item.get("unit"), name)
        if piece_weight and suggestion.get("piece_weight_g") is not None:
            try:
                quantity = float(item.get("amount"))
                suggestion["suggested_quantity"] = round(quantity * float(piece_weight), 1)
                suggestion["suggested_unit"] = "г"
                suggestion["piece_weight_g"] = float(piece_weight)
                suggestion["weight_unknown"] = False
            except (TypeError, ValueError):
                pass

        sku_hint = None
        product = products_map.get(item.get("product_id")) if item.get("product_id") else None
        if product:
            hint = {
                "barcode": product.get("barcode"),
                "brand": product.get("brand"),
                "name": product.get("name"),
            }
            sku_hint = {k: v for k, v in hint.items() if v}

        if suggestion.get("weight_unknown"):
            warnings.append(f"{name}: неизвестен вес 1 шт. Укажите в «Проверь себя».")

        suggested_unit = (suggestion.get("suggested_unit") or "").lower()
        if suggestion.get("sold_as"):
            sold_as = suggestion["sold_as"]
        elif is_sold_by_piece(name):
            sold_as = "piece"
        elif suggested_unit in ("г", "кг"):
            sold_as = "weight"
        elif suggested_unit in ("мл", "л"):
            sold_as = "volume"
        else:
            sold_as = "piece"

        display_name = canonical_name(name)
        items.append({
            "id": item.get("id"),
            "canonical_name": display_name,
            "original_name": name,
            "quantity_original": item.get("amount"),
            "unit_original": item.get("unit"),
            "suggested_quantity": suggestion.get("suggested_quantity"),
            "suggested_unit": suggestion.get("suggested_unit"),
            "sold_as": sold_as,
            "piece_weight_g": suggestion.get("piece_weight_g"),
            "weight_unknown": suggestion.get("weight_unknown", False),
            "notes": item.get("note") or "",
            "sku_hint": sku_hint,
            "product_id": item.get("product_id") or None,
            "recipes": [item.get("recipe_name")] if item.get("recipe_name") else [],
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
            "converted_from_pieces": sum(
                1 for i in merged_items
                if (i.get("unit_original") or "") in ("шт", "зубчик", "пучок")
                and i.get("suggested_unit") == "г"
            ),
            "unknown_weights": sum(1 for i in merged_items if i.get("weight_unknown")),
        },
    }


def _merge_by_canonical(items: list[dict]) -> list[dict]:
    """Склеивает items в один продукт.

    Приоритет:
      1. product_id (если ингредиенты связаны с продуктом) — самый надежный сигнал.
      2. canonical_name + sold_as (нормализация имени).
    """
    by_product: dict[Any, list[dict]] = defaultdict(list)
    orphans: list[dict] = []
    for item in items:
        product_id = item.get("product_id")
        if product_id:
            by_product[product_id].append(item)
        else:
            orphans.append(item)

    result: list[dict] = []

    for product_id, group in by_product.items():
        units = {g.get("suggested_unit") for g in group}
        if len(units) > 1:
            for g in group:
                copy = dict(g)
                copy["merged_via"] = None
                result.append(copy)
            continue

        display_name = None
        for g in group:
            hint = g.get("sku_hint")
            if hint and hint.get("name"):
                display_name = hint["name"]
                break
        if not display_name:
            display_name = normalize_for_connector(group[0].get("canonical_name") or "")

        merged_via = "product_id" if len(group) > 1 else None
        merged = _do_merge(group, display_name, merged_via=merged_via)
        merged["product_id"] = product_id
        result.append(merged)

    by_canon: dict[tuple, list[dict]] = defaultdict(list)
    for item in orphans:
        canon = normalize_for_connector(item.get("canonical_name") or "")
        sold_as = item.get("sold_as", "piece")
        by_canon[(canon, sold_as)].append(item)

    for (canon, _sold_as), group in by_canon.items():
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
