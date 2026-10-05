"""Гибридный поиск продукта по штрих-коду.

Провайдеры:
- OpenFoodFacts (по умолчанию, без ключа)
- Национальный каталог (требует apikey)

Унифицированный ответ:
    {
        "name": str,
        "brand": str | None,
        "image_url": str | None,
        "category": str | None,
        "barcode": str,
        "source": "openfoodfacts" | "national",
    }
"""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from config import (
    CATALOG_API_KEY,
    CATALOG_SOURCE,
    NATIONAL_CATALOG_URL,
    OFF_USER_AGENT,
)

_OFF_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

_OFF_HEADERS = {
    "User-Agent": OFF_USER_AGENT,
    "Accept": "application/json",
}

_TIMEOUT = 10.0


# --- Public API -------------------------------------------------------------

async def lookup_barcode(barcode: str) -> dict:
    """Ищет товар по штрих-коду. Возвращает унифицированный dict.

    Порядок зависит от CATALOG_SOURCE:
    - "openfoodfacts": только ОФФ
    - "national": только НК
    - "auto": пробуем ОФФ, если пусто — НК
    """
    code = (barcode or "").strip()
    if not code or not code.isdigit():
        raise HTTPException(400, "Штрих-код должен содержать только цифры")

    source = CATALOG_SOURCE or "auto"

    if source == "openfoodfacts":
        result = await _lookup_off(code)
        if result:
            return result
        raise HTTPException(404, f"Товар {code} не найден в OpenFoodFacts")

    if source == "national":
        if not CATALOG_API_KEY:
            raise HTTPException(
                400,
                "Для источника 'national' требуется catalog_api_key в настройках",
            )
        result = await _lookup_national(code)
        if result:
            return result
        raise HTTPException(404, f"Товар {code} не найден в Национальном каталоге")

    # auto
    result = await _lookup_off(code)
    if result:
        return result

    if CATALOG_API_KEY:
        result = await _lookup_national(code)
        if result:
            return result

    raise HTTPException(404, f"Товар {code} не найден ни в одном источнике")


# --- Providers --------------------------------------------------------------

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


async def _lookup_national(barcode: str) -> dict | None:
    params = {"apikey": CATALOG_API_KEY, "gtin": barcode}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(NATIONAL_CATALOG_URL, params=params)
            if resp.status_code != 200:
                print(f"[national] http {resp.status_code} for {barcode}")
                return None
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[national] lookup failed for {barcode}: {exc}")
        return None

    # API возвращает {"error_message": ...} при отсутствии товара
    if isinstance(data, dict) and data.get("error_message"):
        return None

    # Успешный ответ — либо сам объект товара, либо {"result": {...}}
    item = data
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        item = data["result"]

    if not isinstance(item, dict):
        return None

    name = (item.get("good_name") or "").strip()
    if not name:
        return None

    # images может быть строкой, списком или словарём
    image_url = None
    images = item.get("good_images") or item.get("good_image")
    if isinstance(images, str):
        image_url = images or None
    elif isinstance(images, list) and images:
        first = images[0]
        image_url = first if isinstance(first, str) else (first or {}).get("url")
    elif isinstance(images, dict):
        image_url = images.get("url") or images.get("original")

    return {
        "name": name,
        "brand": (item.get("brand_name") or "").strip() or None,
        "image_url": image_url,
        "category": (item.get("product_group_name") or item.get("good_category_name") or None),
        "barcode": barcode,
        "source": "national",
    }