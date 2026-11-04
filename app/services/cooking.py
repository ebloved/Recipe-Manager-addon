"""Логика «Готовлю сейчас»: сессия, объединение ингредиентов, план/покупки."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from services.shopping_normalizer import normalize_for_connector
from stores import meal_plan_store, recipe_store, shopping_store
from stores.cooking_sessions import cooking_sessions


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _key(ingredient: dict[str, Any]) -> str:
    name = normalize_for_connector(ingredient.get("name") or "")
    unit = str(ingredient.get("unit") or "").strip().lower()
    return f"{name}|{unit}"


def _recipe_brief(recipe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not recipe:
        return None
    return {
        "id": recipe.get("id"),
        "name": recipe.get("name"),
        "image_url": recipe.get("image_url"),
        "tags": recipe.get("tags") or [],
        "courses": recipe.get("courses") or [],
        "categories": recipe.get("categories") or [],
        "category": recipe.get("category"),
        "servings": recipe.get("servings"),
        "total_time": recipe.get("total_time"),
        "active_time": recipe.get("active_time"),
    }


def merge_ingredients(
    main_ingredients: list[Any],
    side_ingredients: list[Any],
) -> list[dict[str, Any]]:
    """Склеивает ингредиенты двух рецептов по имени+единице."""
    merged: dict[str, dict[str, Any]] = {}

    for source, ingredients in (("main", main_ingredients), ("side", side_ingredients)):
        for raw in ingredients or []:
            if not isinstance(raw, dict) or raw.get("is_heading"):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            key = _key(raw)
            item = merged.get(key)
            amount = _num(raw.get("amount"))
            if item is None:
                merged[key] = {
                    "key": key,
                    "name": name,
                    "amount": raw.get("amount"),
                    "unit": raw.get("unit"),
                    "notes": raw.get("notes"),
                    "optional": bool(raw.get("optional")),
                    "product_id": raw.get("product_id"),
                    "barcode": raw.get("barcode"),
                    "sources": [source],
                }
                continue

            if source not in item["sources"]:
                item["sources"].append(source)
            if amount is not None:
                old = _num(item.get("amount"))
                if old is not None:
                    item["amount"] = old + amount
                elif item.get("amount") in (None, ""):
                    item["amount"] = raw.get("amount")
            item["optional"] = bool(item.get("optional") and raw.get("optional"))
            if raw.get("notes") and raw["notes"] not in (item.get("notes") or ""):
                item["notes"] = "; ".join(
                    p for p in (item.get("notes"), raw.get("notes")) if p
                )
            if not item.get("product_id") and raw.get("product_id"):
                item["product_id"] = raw.get("product_id")
                item["barcode"] = raw.get("barcode")

    return list(merged.values())


async def get_current(user_id: str) -> dict[str, Any]:
    session = await cooking_sessions.get(user_id)
    if session is None:
        return {"active": False, "session": None, "ingredients": [],
                "main_steps": [], "side_steps": []}

    main_recipe = recipe_store.get(session.get("main_recipe_id") or "")
    side_recipe = recipe_store.get(session.get("side_recipe_id") or "")
    if not main_recipe and not side_recipe:
        await cooking_sessions.delete(user_id)
        return {"active": False, "session": None, "ingredients": [],
                "main_steps": [], "side_steps": []}

    ingredients = merge_ingredients(
        (main_recipe or {}).get("ingredients") or [],
        (side_recipe or {}).get("ingredients") or [],
    )
    checked = set(session.get("checked_ingredients") or [])
    for item in ingredients:
        item["checked"] = item["key"] in checked

    return {
        "active": True,
        "session": {
            "id": session["id"],
            "main_recipe_id": session.get("main_recipe_id"),
            "side_recipe_id": session.get("side_recipe_id"),
            "checked_ingredients": [i["key"] for i in ingredients if i["checked"]],
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
        },
        "main_recipe": _recipe_brief(main_recipe),
        "side_recipe": _recipe_brief(side_recipe),
        "ingredients": ingredients,
        "main_steps": list((main_recipe or {}).get("instructions") or []),
        "side_steps": list((side_recipe or {}).get("instructions") or []),
    }


async def set_current(
    user_id: str,
    *,
    main_recipe_id: str | None,
    side_recipe_id: str | None,
) -> dict[str, Any]:
    if not main_recipe_id and not side_recipe_id:
        raise ValueError("main_recipe_id or side_recipe_id is required")
    if main_recipe_id and not recipe_store.get(main_recipe_id):
        raise ValueError("main recipe not found")
    if side_recipe_id and not recipe_store.get(side_recipe_id):
        raise ValueError("side recipe not found")
    await cooking_sessions.upsert(
        user_id,
        main_recipe_id=main_recipe_id or None,
        side_recipe_id=side_recipe_id or None,
    )
    return await get_current(user_id)


async def update_checked(user_id: str, checked: list[str]) -> dict[str, Any]:
    payload = await get_current(user_id)
    if not payload.get("active"):
        raise ValueError("no active cooking session")
    valid = {i["key"] for i in payload.get("ingredients") or []}
    filtered = [key for key in checked if key in valid]
    await cooking_sessions.update_checked(user_id, filtered)
    return await get_current(user_id)


def _meal_type_now() -> str:
    hour = datetime.now().hour
    if hour < 11:
        return "breakfast"
    if hour < 16:
        return "lunch"
    if hour < 22:
        return "dinner"
    return "snack"


async def send_to_plan(user_id: str, meal_type: str | None = None) -> dict[str, Any]:
    payload = await get_current(user_id)
    if not payload.get("active"):
        raise ValueError("no active cooking session")

    date = datetime.now().date().isoformat()
    meal = meal_type or _meal_type_now()
    recipes = [
        payload.get("main_recipe"),
        payload.get("side_recipe"),
    ]
    recipes = [r for r in recipes if r]
    notes = "Готовлю сейчас"
    if payload.get("side_recipe"):
        notes += f" + гарнир: {payload['side_recipe']['name']}"

    entries = []
    for recipe in recipes:
        existing = next(
            (
                e for e in meal_plan_store.entries
                if e.get("owner_id") == user_id
                and e.get("date") == date
                and e.get("meal_type") == meal
                and e.get("recipe_id") == recipe["id"]
            ),
            None,
        )
        if existing:
            entries.append(existing)
            continue
        entry = await meal_plan_store.add({
            "recipe_id": recipe["id"],
            "date": date,
            "meal_type": meal,
            "servings": recipe.get("servings"),
            "notes": notes,
        }, owner_id=user_id)
        entries.append(entry)
    return {"entries": entries, "date": date, "meal_type": meal}


async def send_to_shopping(user_id: str) -> dict[str, int]:
    payload = await get_current(user_id)
    if not payload.get("active"):
        raise ValueError("no active cooking session")
    added = 0
    merged = 0
    for item in payload.get("ingredients") or []:
        if item.get("checked") or item.get("optional"):
            continue
        _, was_merged = await shopping_store.add_or_merge({
            "name": item.get("name"),
            "amount": item.get("amount"),
            "unit": item.get("unit"),
            "note": "Готовлю сейчас",
            "source": "cooking",
        }, owner_id=user_id)
        if was_merged:
            merged += 1
        else:
            added += 1
    return {"added": added, "merged": merged}


async def clear(user_id: str) -> bool:
    return await cooking_sessions.delete(user_id)
