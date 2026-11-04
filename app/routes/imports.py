"""Импорт рецептов: с сайта (scrape), из Markdown (файл / URL / текст).

Изменения относительно предыдущей версии:
  - После парсинга Markdown вызывается `link_recipe_ingredients()` —
    он превращает блоки `product.barcode/uuid` из front matter в реальные
    `product_id` из базы продуктов.
  - Добавлена поддержка batch-импорта: несколько .md в одном запросе
    через `link_many_recipes()` — общий barcode-кэш, один OFF-запрос
    на каждый уникальный продукт.
  - Scrape (с сайта) не линкуется — там нет front matter с product-блоками.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Form, HTTPException, UploadFile, File

from recipe_manager.importer import parse_markdown_recipe
from services.linker import link_many_recipes, link_recipe_ingredients
from services.scraper import fetch_markdown, scrape_recipe
from stores import recipe_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["imports"])


# ---------------------------------------------------------------------------
# Scrape from URL
# ---------------------------------------------------------------------------

@router.post("/api/scrape")
async def api_scrape(url: str = Form(...)):
    """Скрейпит рецепт с сайта. Не сохраняет — возвращает данные для редактора.

    Скрейпинг даёт «сырые» ингредиенты без product-блоков, поэтому
    linker здесь не применяется. Связывание произойдёт, если пользователь
    отредактирует и сохранит рецепт через редактор.
    """
    data = await scrape_recipe(url)
    return {"recipe": data}


# ---------------------------------------------------------------------------
# Import Markdown from URL
# ---------------------------------------------------------------------------

@router.post("/api/recipes/import-url")
async def import_recipe_from_url(url: str = Form(...)):
    """Загружает .md по URL, парсит, линкует ингредиенты, сохраняет."""
    try:
        content = await fetch_markdown(url)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"fetch_failed: {exc}") from exc

    try:
        data = parse_markdown_recipe(content)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    # Связываем ингредиенты с базой продуктов (если есть product-блоки)
    try:
        data = await link_recipe_ingredients(data)
    except Exception as exc:  # noqa: BLE001
        # Не падаем — рецепт сохранится без связок, пользователь свяжет вручную
        logger.warning("Linker упал при импорте из URL: %s", exc)

    # Убираем служебную статистику перед сохранением
    data.pop("_linker_stats", None)

    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Import Markdown from text (paste)
# ---------------------------------------------------------------------------

@router.post("/api/recipes/import-text")
async def import_recipe_from_text(payload: dict[str, Any] = Body(...)):
    """Импорт из вставленного текста.

    Payload: {"markdown_content": "..."}
    """
    md = payload.get("markdown_content")
    if not md or not isinstance(md, str):
        raise HTTPException(400, "'markdown_content' is required")

    try:
        data = parse_markdown_recipe(md)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    try:
        data = await link_recipe_ingredients(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Linker упал при импорте из текста: %s", exc)

    data.pop("_linker_stats", None)

    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Import multiple Markdown files (batch)
# ---------------------------------------------------------------------------

@router.post("/api/recipes/import-batch")
async def import_recipes_batch(files: list[UploadFile] = File(...)):
    """Массовый импорт нескольких .md файлов за один запрос.

    Общий barcode-кэш между рецептами: если в 10 файлах один и тот же
    греческий йогурт, OFF запрашивается один раз.

    Возвращает:
        {
            "imported": N,
            "failed": M,
            "recipes": [{id, name}, ...],
            "errors": [{filename, error}, ...]
        }
    """
    if not files:
        raise HTTPException(400, "Не передано ни одного файла")

    # Читаем и парсим
    parsed_list: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for f in files:
        try:
            raw = await f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp1251", errors="replace")

            recipe = parse_markdown_recipe(text)
            # Запоминаем имя файла для отчёта
            recipe["_source_filename"] = f.filename or "unknown.md"
            parsed_list.append(recipe)
        except Exception as exc:  # noqa: BLE001
            errors.append({"filename": f.filename or "unknown", "error": str(exc)})
            logger.warning("Batch import: %s — %s", f.filename, exc)

    if not parsed_list:
        return {
            "imported": 0,
            "failed": len(errors),
            "recipes": [],
            "errors": errors,
        }

    # Линкуем все разом — общий barcode-кэш
    try:
        parsed_list = await link_many_recipes(parsed_list)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Linker упал в batch-импорте: %s", exc)

    # Сохраняем
    saved: list[dict[str, Any]] = []
    for recipe in parsed_list:
        try:
            recipe.pop("_linker_stats", None)
            recipe.pop("_source_filename", None)
            saved_recipe = await recipe_store.add(recipe)
            saved.append({
                "id": saved_recipe.get("id"),
                "name": saved_recipe.get("name"),
            })
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "filename": recipe.get("_source_filename", "unknown"),
                "error": str(exc),
            })
            logger.warning("Batch import: не удалось сохранить '%s': %s",
                           recipe.get("name"), exc)

    return {
        "imported": len(saved),
        "failed": len(errors),
        "recipes": saved,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@router.get("/api/tags")
async def list_tags():
    """Все уникальные теги из рецептов."""
    return {"tags": recipe_store.all_tags()}