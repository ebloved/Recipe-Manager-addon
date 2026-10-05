"""CRUD рецептов."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from recipe_manager.importer import parse_markdown_recipe
from stores import meal_plan_store, recipe_store

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.get("")
async def list_recipes(q: str | None = None):
    items = recipe_store.get_all()
    if q:
        lower = q.strip().lower()

        def matches(r: dict[str, Any]) -> bool:
            if lower in (r.get("name") or "").lower():
                return True
            if lower in (r.get("description") or "").lower():
                return True
            for key in ("tags", "courses", "categories", "collections"):
                for v in r.get(key) or []:
                    if isinstance(v, str) and lower in v.lower():
                        return True
            for ing in r.get("ingredients") or []:
                name = ing.get("name") if isinstance(ing, dict) else str(ing)
                if name and lower in str(name).lower():
                    return True
            return False

        items = [r for r in items if matches(r)]
    return {"recipes": items, "count": len(items)}


@router.get("/{recipe_id}")
async def get_recipe(recipe_id: str):
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


@router.post("")
async def create_recipe(payload: dict[str, Any] = Body(...)):
    md = payload.get("markdown_content")
    explicit = {k: v for k, v in payload.items() if k != "markdown_content"}
    if md:
        try:
            parsed = parse_markdown_recipe(md)
        except ValueError as exc:
            raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc
        data = {**parsed, **explicit}
    else:
        if not explicit.get("name"):
            raise HTTPException(400, "Either 'name' or 'markdown_content' is required")
        data = explicit
    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


@router.patch("/{recipe_id}")
async def update_recipe(recipe_id: str, patch: dict[str, Any] = Body(...)):
    recipe = await recipe_store.update(recipe_id, patch)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


@router.delete("/{recipe_id}")
async def delete_recipe(recipe_id: str):
    ok = await recipe_store.delete(recipe_id)
    if not ok:
        raise HTTPException(404, "Recipe not found")
    removed = await meal_plan_store.delete_by_recipe(recipe_id)
    return {"deleted": True, "meal_plan_entries_removed": removed}


@router.get("/-/tags", include_in_schema=False)
async def list_tags_inline():
    return {"tags": recipe_store.all_tags()}