"""Извлечение рецептов с веб-сайтов и загрузка Markdown по URL."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from helpers import (
    extract_servings_count,
    first_or_str,
    safe_call,
    to_int_minutes,
)

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}

_FETCH_MD_HEADERS = {
    "User-Agent": "HomeAssistant-RecipeManager/1.0",
    "Accept": "text/markdown,text/plain,text/*;q=0.9,*/*;q=0.5",
}


async def fetch_markdown(url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=_FETCH_MD_HEADERS)
        if resp.status_code != 200:
            raise HTTPException(502, f"HTTP {resp.status_code} fetching {url}")
        return resp.text


async def scrape_recipe(url: str) -> dict[str, Any]:
    try:
        from recipe_scrapers import scrape_html  # type: ignore[import]
    except ImportError as exc:
        raise HTTPException(500, f"recipe-scrapers not installed: {exc}") from exc

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=_SCRAPE_HEADERS
    ) as client:
        try:
            resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"fetch_failed: {exc}") from exc
        if resp.status_code != 200:
            raise HTTPException(502, f"HTTP {resp.status_code} fetching {url}")
        html = resp.text

    try:
        scraper = scrape_html(html, org_url=url, wild_mode=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"scrape_failed: {exc}") from exc

    name = (safe_call(scraper.title) or "").strip()
    if not name:
        raise HTTPException(502, "Не удалось извлечь название рецепта")

    ingredients_raw = safe_call(scraper.ingredients) or []
    ingredients = [str(s).strip() for s in ingredients_raw if s and str(s).strip()]

    instructions = safe_call(scraper.instructions_list) or []
    if not instructions:
        raw = safe_call(scraper.instructions) or ""
        instructions = [s.strip() for s in str(raw).split("\n") if s.strip()]

    servings_text = safe_call(scraper.yields)
    keywords = safe_call(scraper.keywords) or []
    if isinstance(keywords, str):
        tags = [t.strip().lower() for t in keywords.split(",") if t.strip()]
    else:
        tags = [str(t).strip().lower() for t in keywords if str(t).strip()]

    return {
        "name": name,
        "description": safe_call(scraper.description),
        "source_url": url,
        "image_url": safe_call(scraper.image),
        "servings": extract_servings_count(servings_text),
        "servings_text": str(servings_text) if servings_text else None,
        "prep_time": to_int_minutes(safe_call(scraper.prep_time)),
        "cook_time": to_int_minutes(safe_call(scraper.cook_time)),
        "total_time": to_int_minutes(safe_call(scraper.total_time)),
        "cuisine": first_or_str(safe_call(scraper.cuisine)),
        "category": first_or_str(safe_call(scraper.category)),
        "ingredients": ingredients,
        "instructions": instructions,
        "tags": tags,
    }