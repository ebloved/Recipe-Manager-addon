"""Поиск продукта по штрих-коду через OpenFoodFacts.

Унифицированный ответ:
    {
        "name": str,
        "brand": str | None,
        "image_url": str | None,
        "category": str | None,
        "barcode": str,
        "source": "openfoodfacts",
    }
"""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from config import OFF_USER_AGENT

_OFF_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

_OFF_HEADERS = {
    "User-Agent": OFF_USER_AGENT,
    "Accept": "application/json",
}

_TIMEOUT = 10.0


# --- Public API -------------------------------------------------------------

async def lookup_barcode(barcode: str) -> dict:
    """Ищет товар по штрих-коду в OpenFoodFacts.

    Возвращает унифицированный dict. Бросает HTTPException, если товар не найден.
    """
    code = (barcode or "").strip()
    if not code or not code.isdigit():
        raise HTTPException(400, "Штрих-код должен содержать только цифры")

    result = await _lookup_off(code)
    if result:
        return result

    raise HTTPException(404, f"Товар {code} не найден в OpenFoodFacts")


# --- Provider ---------------------------------------------------------------

async def _lookup_off(barcode: str) -> dict | None:
    url = _OFF_PRODUCT_URL.format(barcode=barcode)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=_OFF_HEADERS)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[off] lookup failed for {barcode}: {exc}")
        return None

    if data.get("status") != 1:
        return None

    product = data.get("product") or {}
    name = (
        product.get("product_name")
        or product.get("product_name_ru")
        or product.get("generic_name")
        or ""
    ).strip()
    if not name:
        return None

    categories = (product.get("categories") or "").split(",")
    category = categories[0].strip() if categories else None

    return {
        "name": name,
        "brand": (product.get("brands") or "").split(",")[0].strip() or None,
        "image_url": product.get("image_url") or product.get("image_front_url") or None,
        "category": category,
        "barcode": barcode,
        "source": "openfoodfacts",
    }