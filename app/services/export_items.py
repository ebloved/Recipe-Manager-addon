"""Read-only экспорт списка покупок и продуктов из плана питания.

Формат не зависит от магазина: внешний сервис получает названия,
количества, единицы, product_id/штрихкоды и контекст рецептов.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.pantry import is_pantry_ingredient
from services.piece_weights import (
    get_default_weight,
    is_piece_unit,
    is_sold_by_piece,
    suggest_unit_and_quantity,
)
from services.recipe_standard import canonical_name
from services.shopping_normalizer import normalize_for_connector
from stores import ingredients_store, meal_plan_store, recipe_store, shopping_store

_ALLOWED_SOURCES = {"shopping", "meal_plan", "both"}
_PIECE_UNITS = {"шт", "штук", "штука", "штуки", "зубчик", "зубчика", "пучок", "пучка"}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _scale_amount(amount: Any, multiplier: float) -> Any:
    if multiplier == 1:
        return amount
    try:
        value = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        return amount
    value *= multiplier
    return int(value) if value.is_integer() else round(value, 2)


def _product_info(product_id: Any) -> dict[str, Any] | None:
    if not product_id:
        return None
    try:
        product = ingredients_store.get_active(str(product_id))
    except Exception:  # noqa: BLE001
        return None
    return product


def _suggestion(
    name: str,
    amount: Any,
    unit: str | None,
    user_weights: dict[str, Any],
) -> dict[str, Any]:
    suggestion = suggest_unit_and_quantity(amount, unit, name)
    piece_weight = user_weights.get(name) or get_default_weight(name)
    if piece_weight:
        try:
            quantity = float(str(amount).replace(",", "."))
        except (TypeError, ValueError):
            quantity = None
        if quantity is not None and (
            suggestion.get("piece_weight_g") is not None
            or (unit or "").strip().lower() in _PIECE_UNITS
        ):
            suggestion["suggested_quantity"] = round(quantity * float(piece_weight), 1)
            suggestion["suggested_unit"] = "г"
            suggestion["piece_weight_g"] = float(piece_weight)
            suggestion["weight_unknown"] = False
    if suggestion.get("sold_as"):
        sold_as = suggestion["sold_as"]
    elif is_sold_by_piece(name):
        sold_as = "piece"
    else:
        suggested_unit = str(suggestion.get("suggested_unit") or unit or "").lower()
        if suggested_unit in ("г", "гр", "кг", "kg", "g"):
            sold_as = "weight"
        elif suggested_unit in ("мл", "л", "ml", "l"):
            sold_as = "volume"
        else:
            sold_as = "piece"
    return {
        "suggested_quantity": suggestion.get("suggested_quantity"),
        "suggested_unit": suggestion.get("suggested_unit") or unit,
        "piece_weight_g": suggestion.get("piece_weight_g"),
        "weight_unknown": bool(suggestion.get("weight_unknown")),
        "sold_as": sold_as,
    }


def _component(
    *,
    source: str,
    name: str,
    amount: Any,
    unit: str | None,
    product: dict[str, Any] | None,
    user_weights: dict[str, Any],
    checked: bool = False,
    recipe: dict[str, Any] | None = None,
    notes: str | None = None,
    pantry: bool | None = None,
    shopping_item_id: str | None = None,
) -> dict[str, Any]:
    suggestion = _suggestion(name, amount, unit, user_weights)
    if pantry is None:
        pantry = is_pantry_ingredient({"name": name}, product)
    group = None
    if product and product.get("id"):
        try:
            group = ingredients_store.group_for_product(str(product["id"]))
        except Exception:  # noqa: BLE001
            group = None
    members = (group or {}).get("members") or []
    variant_barcodes = sorted({
        str(member.get("barcode"))
        for member in members
        if member.get("barcode")
    })
    variant_product_ids = sorted({
        str(member.get("id"))
        for member in members
        if member.get("id")
    })
    return {
        "source": source,
        "name": name,
        "canonical_name": canonical_name(name),
        "amount": amount,
        "unit": unit,
        "checked": bool(checked),
        "recipe": recipe,
        "notes": notes or None,
        "product_id": (product or {}).get("id") or None,
        "barcode": (product or {}).get("barcode") or None,
        "brand": (product or {}).get("brand") or None,
        "category": (product or {}).get("category") or None,
        "image_url": (product or {}).get("image_url") or None,
        "group_id": (group or {}).get("id") or (product or {}).get("group_id"),
        "identity_key": (product or {}).get("identity_key"),
        "variant_barcodes": variant_barcodes,
        "variant_product_ids": variant_product_ids,
        "pantry": bool(pantry),
        "essential": not bool(pantry),
        "shopping_item_id": shopping_item_id,
        **suggestion,
    }


def _shopping_components(
    owner_id: str,
    *,
    include_checked: bool,
    user_weights: dict[str, Any],
) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    items = shopping_store.get_all(
        owner_id=owner_id,
        only_active=not include_checked,
    )
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        product = _product_info(item.get("product_id"))
        recipe = None
        if item.get("recipe_id") or item.get("recipe_name"):
            recipe = {
                "id": item.get("recipe_id"),
                "name": item.get("recipe_name"),
            }
        components.append(_component(
            source="shopping",
            name=name,
            amount=item.get("amount"),
            unit=item.get("unit"),
            product=product,
            user_weights=user_weights,
            checked=bool(item.get("checked")),
            recipe=recipe,
            notes=item.get("note"),
            shopping_item_id=item.get("id"),
        ))
    return components


def _meal_plan_components(
    owner_id: str,
    start: str,
    end: str,
    *,
    user_weights: dict[str, Any],
    include_pantry: bool = False,
) -> tuple[list[dict[str, Any]], list[str], int]:
    components: list[dict[str, Any]] = []
    warnings: list[str] = []
    pantry_excluded = 0
    entries = meal_plan_store.get_range(start, end)
    for entry in entries:
        recipe = recipe_store.get(entry.get("recipe_id") or "")
        if not recipe:
            warnings.append(f"Рецепт {entry.get('recipe_id')} не найден — пропущен")
            continue
        if recipe.get("personal_of") and recipe.get("owner_id") != owner_id:
            continue
        recipe_servings = _num(recipe.get("servings"))
        entry_servings = _num(entry.get("servings"))
        multiplier = 1.0
        if entry_servings and recipe_servings:
            multiplier = entry_servings / recipe_servings
        elif entry_servings and not recipe_servings:
            warnings.append(
                f"[{recipe.get('name') or entry.get('recipe_id')}] "
                "у рецепта не указаны порции — количество не масштабировано"
            )
        recipe_ctx = {
            "id": recipe.get("id"),
            "name": recipe.get("name"),
            "date": entry.get("date"),
            "meal_type": entry.get("meal_type"),
            "servings": entry.get("servings"),
        }
        raw = recipe.get("ingredients") or []
        for index, ingredient in enumerate(raw):
            if isinstance(ingredient, str):
                ing = {"name": ingredient, "amount": None, "unit": None}
            elif isinstance(ingredient, dict):
                ing = ingredient
            else:
                continue
            name = (ing.get("name") or "").strip()
            if not name or ing.get("is_heading") or name.startswith("#"):
                continue
            product = _product_info(ing.get("product_id"))
            pantry = is_pantry_ingredient(ing, product)
            if pantry and not include_pantry:
                pantry_excluded += 1
                continue
            components.append(_component(
                source="meal_plan",
                name=name,
                amount=_scale_amount(ing.get("amount"), multiplier),
                unit=ing.get("unit"),
                product=product,
                user_weights=user_weights,
                checked=False,
                recipe=recipe_ctx,
                notes=ing.get("notes"),
                pantry=pantry,
            ))
    return components, warnings, pantry_excluded


def _merge_key(component: dict[str, Any], index: int, merge: bool) -> tuple:
    if not merge:
        return ("row", index)
    if component.get("group_id"):
        return ("group", component["group_id"])
    if component.get("product_id"):
        return ("pid", component["product_id"])
    return (
        "name",
        normalize_for_connector(component.get("canonical_name") or component.get("name") or ""),
        (component.get("suggested_unit") or component.get("unit") or "").lower(),
        component.get("sold_as") or "piece",
    )


def _merge_components(
    components: list[dict[str, Any]],
    *,
    merge: bool,
) -> list[dict[str, Any]]:
    items: dict[tuple, dict[str, Any]] = {}
    for index, component in enumerate(components):
        key = _merge_key(component, index, merge)
        existing = items.get(key)
        if existing is None:
            items[key] = {
                "name": component.get("name"),
                "canonical_name": normalize_for_connector(
                    component.get("canonical_name") or component.get("name") or ""
                ),
                "amount": component.get("amount"),
                "unit": component.get("unit"),
                "suggested_quantity": component.get("suggested_quantity"),
                "suggested_unit": component.get("suggested_unit"),
                "sold_as": component.get("sold_as"),
                "piece_weight_g": component.get("piece_weight_g"),
                "weight_unknown": component.get("weight_unknown", False),
                "product_id": component.get("product_id"),
                "barcode": component.get("barcode"),
                "brand": component.get("brand"),
                "category": component.get("category"),
                "image_url": component.get("image_url"),
                "group_id": component.get("group_id"),
                "identity_key": component.get("identity_key"),
                "variant_barcodes": list(component.get("variant_barcodes") or []),
                "variant_product_ids": list(component.get("variant_product_ids") or []),
                "pantry": bool(component.get("pantry")),
                "essential": bool(component.get("essential", True)),
                "shopping_item_ids": [],
                "checked": component.get("checked", False),
                "sources": {component.get("source")},
                "recipes": [],
                "components": [component],
            }
            if component.get("recipe"):
                items[key]["recipes"].append(component["recipe"])
            continue

        existing["components"].append(component)
        existing["sources"].add(component.get("source"))
        if component.get("recipe"):
            existing["recipes"].append(component["recipe"])
        if not existing.get("product_id") and component.get("product_id"):
            existing["product_id"] = component["product_id"]
            existing["barcode"] = component.get("barcode")
            existing["brand"] = component.get("brand")
            existing["category"] = component.get("category")
            existing["image_url"] = component.get("image_url")
        if not existing.get("group_id") and component.get("group_id"):
            existing["group_id"] = component["group_id"]
        if not existing.get("identity_key") and component.get("identity_key"):
            existing["identity_key"] = component["identity_key"]
        existing["variant_barcodes"] = sorted({
            *(existing.get("variant_barcodes") or []),
            *(component.get("variant_barcodes") or []),
        })
        existing["variant_product_ids"] = sorted({
            *(existing.get("variant_product_ids") or []),
            *(component.get("variant_product_ids") or []),
        })
        existing["weight_unknown"] = bool(
            existing.get("weight_unknown") or component.get("weight_unknown")
        )
        existing["pantry"] = bool(
            existing.get("pantry") and component.get("pantry")
        )
        existing["essential"] = not existing["pantry"]
        # Суммируем только количества в одной и той же единице.
        old_unit = (existing.get("unit") or "").strip().lower()
        new_unit = (component.get("unit") or "").strip().lower()
        old_q = _num(existing.get("suggested_quantity"))
        new_q = _num(component.get("suggested_quantity"))
        old_s_unit = (existing.get("suggested_unit") or "").strip().lower()
        new_s_unit = (component.get("suggested_unit") or "").strip().lower()
        if old_q is not None and new_q is not None and old_s_unit == new_s_unit:
            existing["suggested_quantity"] = round(old_q + new_q, 2)
        else:
            existing["suggested_quantity"] = None
        old_amount = _num(existing.get("amount"))
        new_amount = _num(component.get("amount"))
        if old_amount is not None and new_amount is not None and old_unit == new_unit:
            existing["amount"] = round(old_amount + new_amount, 2)
        else:
            existing["amount"] = None
            existing["unit"] = None
        if component.get("source") == "shopping":
            existing["checked"] = bool(existing.get("checked") and component.get("checked"))
        elif not existing.get("sources") or "shopping" not in existing["sources"]:
            existing["checked"] = False

    result: list[dict[str, Any]] = []
    for item in items.values():
        # Уникальные рецепты по (id, date, meal_type).
        seen = set()
        recipes = []
        for recipe in item.get("recipes") or []:
            key = (recipe.get("id"), recipe.get("date"), recipe.get("meal_type"))
            if key in seen:
                continue
            seen.add(key)
            recipes.append(recipe)
        item["recipes"] = recipes
        item["sources"] = sorted(item["sources"])
        item["shopping_item_ids"] = sorted({
            c.get("shopping_item_id")
            for c in item["components"]
            if c.get("shopping_item_id")
        })
        item["shopping_item_id"] = (
            item["shopping_item_ids"][0]
            if len(item["shopping_item_ids"]) == 1
            else None
        )
        item["components"] = item["components"]
        notes = [
            c.get("notes") for c in item["components"]
            if c.get("notes")
        ]
        item["notes"] = "; ".join(dict.fromkeys(notes)) or None
        result.append(item)
    result.sort(key=lambda i: (i.get("category") or "", i.get("canonical_name") or ""))
    return result


def build_export(
    owner_id: str,
    *,
    source: str = "both",
    start: str | None = None,
    end: str | None = None,
    include_checked: bool = False,
    merge: bool = True,
    include_recipes: bool = True,
    include_pantry: bool = False,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = (source or "both").strip().lower()
    if source not in _ALLOWED_SOURCES:
        raise ValueError("source must be shopping, meal_plan or both")

    today = date.today()
    if source in ("meal_plan", "both"):
        start = (start or today.isoformat()).strip()
        end = (end or (today + timedelta(days=7)).isoformat()).strip()
        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except ValueError as exc:
            raise ValueError("start/end must be YYYY-MM-DD") from exc
        if end_date < start_date:
            raise ValueError("end must be >= start")
        if (end_date - start_date).days > 62:
            raise ValueError("range is too large (max 62 days)")
    else:
        start = end = None

    user_weights = (user or {}).get("piece_weights") or {}
    components: list[dict[str, Any]] = []
    warnings: list[str] = []
    pantry_excluded = 0

    if source in ("shopping", "both"):
        components.extend(_shopping_components(
            owner_id,
            include_checked=include_checked,
            user_weights=user_weights,
        ))
    if source in ("meal_plan", "both"):
        meal_components, meal_warnings, pantry_excluded = _meal_plan_components(
            owner_id,
            start,
            end,
            user_weights=user_weights,
            include_pantry=include_pantry,
        )
        components.extend(meal_components)
        warnings.extend(meal_warnings)

    items = _merge_components(components, merge=merge)
    if not include_recipes:
        for item in items:
            item["recipes"] = []
            for component in item["components"]:
                component.pop("recipe", None)

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "range": {"start": start, "end": end} if start and end else None,
        "items": items,
        "warnings": warnings,
        "counts": {
            "shopping": sum(1 for c in components if c.get("source") == "shopping"),
            "meal_plan": sum(1 for c in components if c.get("source") == "meal_plan"),
            "pantry_excluded": pantry_excluded,
            "total": len(items),
        },
    }
    digest_src = json.dumps(
        {
            "source": source,
            "range": payload["range"],
            "include_checked": include_checked,
            "merge": merge,
            "include_recipes": include_recipes,
            "include_pantry": include_pantry,
            "items": items,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    payload["revision"] = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()
    return payload
