"""Добавление ингредиентов рецепта в список покупок.

Вынесено из routes/shopping.py, чтобы недельный план мог переиспользовать
ту же логику с множителем порций.
"""
from __future__ import annotations

from typing import Any

from stores import ingredients_store, recipe_store, shopping_store


def _scale_amount(amount: Any, mult: float) -> Any:
    try:
        num = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        return amount
    result = num * mult
    if result.is_integer():
        return int(result)
    return round(result, 2)


async def add_recipe_ingredients_to_shopping(
    recipe: dict[str, Any],
    *,
    owner_id: str,
    multiplier: float = 1.0,
    ingredient_indices: list[int] | None = None,
) -> dict[str, int]:
    """Добавляет ингредиенты рецепта в покупки и объединяет дубли."""
    recipe_id = recipe.get("id")
    raw = recipe.get("ingredients") or []
    normalized = [
        ({"name": i, "amount": None, "unit": None, "notes": None}
         if isinstance(i, str) else i)
        for i in raw
    ]

    if ingredient_indices is None:
        selected = [
            (idx, ing) for idx, ing in enumerate(normalized)
            if not ing.get("is_heading") and not (ing.get("name") or "").startswith("#")
        ]
    else:
        wanted = set(int(i) for i in ingredient_indices)
        selected = [(idx, normalized[idx]) for idx in wanted if 0 <= idx < len(normalized)]

    products_by_id: dict[str, dict[str, Any]] = {}
    try:
        raw_products = getattr(ingredients_store, "products", None) or {}
        products = raw_products.values() if isinstance(raw_products, dict) else raw_products
        for product in products:
            if isinstance(product, dict):
                pid = product.get("id")
                if pid:
                    products_by_id[pid] = product
    except Exception:  # noqa: BLE001
        products_by_id = {}

    added = 0
    merged = 0
    for _, ing in selected:
        name = (ing.get("name") or "").strip()
        if not name:
            continue
        amount = ing.get("amount")
        if amount and multiplier != 1:
            amount = _scale_amount(amount, multiplier)
        product = products_by_id.get(ing.get("product_id")) if ing.get("product_id") else None
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
        _, was_merged = await shopping_store.add_or_merge(item_data, owner_id=owner_id)
        if was_merged:
            merged += 1
        else:
            added += 1

    return {"added": added, "merged": merged, "total": added + merged}


async def add_recipe_id_to_shopping(
    recipe_id: str,
    *,
    owner_id: str,
    multiplier: float = 1.0,
) -> dict[str, int]:
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        return {"added": 0, "merged": 0, "total": 0}
    return await add_recipe_ingredients_to_shopping(
        recipe, owner_id=owner_id, multiplier=multiplier
    )
