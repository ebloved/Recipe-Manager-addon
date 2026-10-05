"""Импорт рецептов: с сайта (scrape), из Markdown по URL."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException

from recipe_manager.importer import parse_markdown_recipe
from services.scraper import fetch_markdown, scrape_recipe
from stores import recipe_store

router = APIRouter(tags=["imports"])


@router.post("/api/scrape")
async def api_scrape(url: str = Form(...)):
    data = await scrape_recipe(url)
    return {"recipe": data}


@router.post("/api/recipes/import-url")
async def import_recipe_from_url(url: str = Form(...)):
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
    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


@router.get("/api/tags")
async def list_tags():
    return {"tags": recipe_store.all_tags()}