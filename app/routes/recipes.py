"""CRUD рецептов + экспорт/импорт .md.

Изменения относительно предыдущей версии:
  - В `POST /api/recipes` и `PUT /{id}/import-md` после парсинга Markdown
    вызывается `link_recipe_ingredients()` — блоки `product.barcode/uuid`
    из front matter превращаются в `product_id` из базы продуктов.
  - Эндпоинт `POST /api/recipes/import-url` УБРАН отсюда — он переехал
    в `routes/imports.py` (вместе с `import-text` и `import-batch`).
  - Эндпоинт `GET /api/tags` тоже в `imports.py` — здесь его больше нет,
    чтобы не было двойной регистрации.
  - Всё, что касается парсинга и массового импорта, живёт в imports.py;
    recipes.py отвечает только за CRUD над уже сохранёнными рецептами
    и за экспорт/импорт отдельного рецепта.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from recipe_manager.importer import parse_markdown_recipe
from services.linker import link_recipe_ingredients
from services.md_export import recipe_filename, recipe_to_md
from stores import meal_plan_store, recipe_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

@router.get("")
async def list_recipes(q: str | None = None):
    """Возвращает список рецептов с опциональным поиском по имени/тегам/ингредиентам."""
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
    """Возвращает один рецепт по id."""
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post("")
async def create_recipe(payload: dict[str, Any] = Body(...)):
    """Создаёт рецепт.

    Два режима:
      - markdown_content задан → парсим Markdown, линкуем ингредиенты,
        мержим с явными полями (явные имеют приоритет).
      - markdown_content нет → создаём из явных полей (name обязателен).
    """
    md = payload.get("markdown_content")
    explicit = {k: v for k, v in payload.items() if k != "markdown_content"}

    if md:
        try:
            parsed = parse_markdown_recipe(md)
        except ValueError as exc:
            raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

        # Связываем product.barcode/uuid с реальными product_id из store
        try:
            parsed = await link_recipe_ingredients(parsed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Linker упал при создании из Markdown: %s", exc)

        # Убираем служебную статистику перед сохранением
        parsed.pop("_linker_stats", None)

        data = {**parsed, **explicit}
    else:
        if not explicit.get("name"):
            raise HTTPException(400, "Either 'name' or 'markdown_content' is required")

        # Если среди явных полей есть ingredients с product-блоками —
        # прогоним их через линкер тоже.
        if isinstance(explicit.get("ingredients"), list):
            wrapper = {"name": explicit["name"], "ingredients": explicit["ingredients"]}
            try:
                wrapper = await link_recipe_ingredients(wrapper)
                explicit["ingredients"] = wrapper.get("ingredients", explicit["ingredients"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Linker упал при создании из явных полей: %s", exc)

        data = explicit

    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch("/{recipe_id}")
async def update_recipe(recipe_id: str, patch: dict[str, Any] = Body(...)):
    """Обновляет рецепт частично.

    Если в patch переданы ingredients с product-блоками — линкуем.
    """
    existing = recipe_store.get(recipe_id)
    if not existing:
        raise HTTPException(404, "Recipe not found")

    if isinstance(patch.get("ingredients"), list):
        wrapper = {
            "name": patch.get("name") or existing.get("name"),
            "ingredients": patch["ingredients"],
        }
        try:
            wrapper = await link_recipe_ingredients(wrapper)
            patch = {**patch, "ingredients": wrapper.get("ingredients", patch["ingredients"])}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Linker упал при обновлении рецепта: %s", exc)

    recipe = await recipe_store.update(recipe_id, patch)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{recipe_id}")
async def delete_recipe(recipe_id: str):
    """Удаляет рецепт и связанные записи плана питания."""
    ok = await recipe_store.delete(recipe_id)
    if not ok:
        raise HTTPException(404, "Recipe not found")
    removed = await meal_plan_store.delete_by_recipe(recipe_id)
    return {"deleted": True, "meal_plan_entries_removed": removed}


# ---------------------------------------------------------------------------
# Export to Markdown
# ---------------------------------------------------------------------------

@router.get("/{recipe_id}/export.md")
async def export_recipe_md(recipe_id: str):
    """Отдаёт .md файл с рецептом.

    Формат имени: <transliterated-slug>_<8-символов-id>.md
    Содержимое: YAML front matter + тело, включая блоки product.barcode
    для связанных ингредиентов (см. services/md_export.py).
    """
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    md = recipe_to_md(recipe)
    filename = recipe_filename(recipe)

    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Import from Markdown (replace existing recipe)
# ---------------------------------------------------------------------------

@router.put("/{recipe_id}/import-md")
async def import_recipe_md(recipe_id: str, payload: dict[str, Any] = Body(...)):
    """Заменяет поля существующего рецепта содержимым Markdown.

    Payload: {"markdown_content": "..."}

    Сохраняет `id` и `created_at` исходного рецепта.
    Ингредиенты линкуются через linker (обрабатывает product.barcode/uuid).
    """
    md = payload.get("markdown_content")
    if not md or not isinstance(md, str):
        raise HTTPException(400, "'markdown_content' is required")

    existing = recipe_store.get(recipe_id)
    if not existing:
        raise HTTPException(404, "Recipe not found")

    try:
        parsed = parse_markdown_recipe(md)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    # Связываем продукт-блоки с product_id
    try:
        parsed = await link_recipe_ingredients(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Linker упал при import-md: %s", exc)

    parsed.pop("_linker_stats", None)

    # Сохраняем неизменяемые поля
    parsed["id"] = existing.get("id")
    parsed["created_at"] = existing.get("created_at")

    updated = await recipe_store.update(recipe_id, parsed)
    if not updated:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": updated}


# ---------------------------------------------------------------------------
# Import from Markdown (create new — короткий алиас для recipe_store.add)
# ---------------------------------------------------------------------------

@router.post("/-/from-markdown")
async def create_from_markdown(payload: dict[str, Any] = Body(...)):
    """Создаёт новый рецепт из Markdown.

    Отличие от POST /api/recipes с markdown_content:
      - всегда создаёт новый рецепт (не мержит с явными полями),
      - не принимает дополнительных полей — только markdown_content.

    Удобно для быстрых интеграций и скриптов.
    """
    md = payload.get("markdown_content")
    if not md or not isinstance(md, str):
        raise HTTPException(400, "'markdown_content' is required")

    try:
        parsed = parse_markdown_recipe(md)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    try:
        parsed = await link_recipe_ingredients(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Linker упал при create-from-markdown: %s", exc)

    parsed.pop("_linker_stats", None)

    recipe = await recipe_store.add(parsed)
    return {"recipe": recipe}