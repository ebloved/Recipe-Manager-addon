"""План питания."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from stores import meal_plan_store, recipe_store

router = APIRouter(prefix="/api/meal-plan", tags=["meal-plan"])

_ALLOWED_MEALS = {"breakfast", "lunch", "snack", "dinner"}


@router.get("")
async def list_meal_plan(start: str, end: str):
    """Возвращает записи плана за период + данные рецепта для отображения."""
    entries = meal_plan_store.get_range(start, end)
    result = []
    for e in entries:
        recipe = recipe_store.get(e.get("recipe_id") or "")
        result.append({
            **e,
            "recipe_name": recipe.get("name") if recipe else None,
            "recipe_image": recipe.get("image_url") if recipe else None,
            "recipe_nutrition": recipe.get("nutrition") if recipe else None,
            "recipe_servings": recipe.get("servings") if recipe else None,
        })
    return {"entries": result, "count": len(result)}


@router.post("")
async def add_meal_plan_entry(payload: dict[str, Any] = Body(...)):
    recipe_id = payload.get("recipe_id")
    date = payload.get("date")
    meal_type = payload.get("meal_type")
    if not recipe_id or not date or not meal_type:
        raise HTTPException(400, "recipe_id, date, meal_type are required")
    if not recipe_store.get(recipe_id):
        raise HTTPException(404, "Recipe not found")
    if meal_type not in _ALLOWED_MEALS:
        raise HTTPException(400, "Invalid meal_type")
    entry = await meal_plan_store.add({
        "recipe_id": recipe_id,
        "date": date,
        "meal_type": meal_type,
        "servings": payload.get("servings"),
        "notes": payload.get("notes"),
    })
    return {"entry": entry}


@router.patch("/{entry_id}")
async def update_meal_plan_entry(entry_id: str, patch: dict[str, Any] = Body(...)):
    allowed = {k: v for k, v in patch.items() if k in ("servings", "notes", "date", "meal_type")}
    entry = await meal_plan_store.update(entry_id, allowed)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return {"entry": entry}


@router.delete("/{entry_id}")
async def delete_meal_plan_entry(entry_id: str):
    ok = await meal_plan_store.delete(entry_id)
    if not ok:
        raise HTTPException(404, "Entry not found")
    return {"deleted": True}