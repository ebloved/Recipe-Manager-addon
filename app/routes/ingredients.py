"""API справочника продуктов.

CRUD, поиск, импорт из Open Food Facts, сканирование штрих-кодов,
контрибуция (отправка в OFF), управление алиасами.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from services.off_client import (
    cache_clear,
    cache_stats,
    can_contribute,
    contribute_product,
    fetch_product,
)
from stores import (
    ingredients_store,
    is_internal_barcode,
    off_product_id,
)

router = APIRouter(prefix="/api/ingredients", tags=["ingredients"])


# --- Список и чтение ------------------------------------------------------

@router.get("")
async def list_ingredients(
    q: str | None = Query(None, description="Подстрочный поиск по name и aliases"),
    category: str | None = Query(None),
    include_deleted: bool = Query(False),
):
    if q:
        items = ingredients_store.search(q, limit=200)
    else:
        items = ingredients_store.get_all(include_deleted=include_deleted)

    if category:
        items = [p for p in items if p.get("category") == category]

    return {
        "products": items,
        "count": len(items),
    }


@router.get("/categories")
async def list_categories():
    return {"categories": ingredients_store.all_categories()}


@router.get("/{product_id}")
async def get_ingredient(product_id: str):
    p = ingredients_store.get(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return {"product": p}


# --- CRUD -----------------------------------------------------------------

@router.post("")
async def create_ingredient(payload: dict[str, Any] = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")

    barcode = (payload.get("barcode") or "").strip()
    # Если продукт с таким barcode уже есть — вернём его
    if barcode:
        existing = ingredients_store.find_by_barcode(barcode)
        if existing:
            raise HTTPException(
                409,
                f"Продукт с таким штрих-кодом уже есть: {existing.get('name')}",
            )

    product = await ingredients_store.add(payload)
    return {"product": product}


@router.patch("/{product_id}")
async def update_ingredient(product_id: str, patch: dict[str, Any] = Body(...)):
    p = await ingredients_store.update(product_id, patch)
    if not p:
        raise HTTPException(404, "Product not found")
    return {"product": p}


@router.delete("/{product_id}")
async def delete_ingredient(product_id: str):
    ok = await ingredients_store.soft_delete(product_id)
    if not ok:
        raise HTTPException(404, "Product not found")
    return {"deleted": True}


@router.post("/{product_id}/restore")
async def restore_ingredient(product_id: str):
    ok = await ingredients_store.restore(product_id)
    if not ok:
        raise HTTPException(404, "Product not found")
    return {"restored": True}


# --- Алиасы ---------------------------------------------------------------

@router.post("/{product_id}/aliases")
async def add_alias(product_id: str, payload: dict[str, Any] = Body(...)):
    alias = (payload.get("alias") or "").strip()
    if not alias:
        raise HTTPException(400, "'alias' is required")
    ok = await ingredients_store.add_alias(product_id, alias)
    if not ok:
        raise HTTPException(409, "Alias already exists or product not found")
    return {"product": ingredients_store.get(product_id)}


@router.delete("/{product_id}/aliases")
async def remove_alias(product_id: str, alias: str = Query(...)):
    ok = await ingredients_store.remove_alias(product_id, alias)
    if not ok:
        raise HTTPException(404, "Alias not found")
    return {"product": ingredients_store.get(product_id)}


# --- Open Food Facts ------------------------------------------------------

@router.post("/lookup")
async def lookup_in_off(payload: dict[str, Any] = Body(...)):
    """Поиск продукта в OFF по штрих-коду. НЕ сохраняет.

    Возвращает статус + найденные данные. Если найдено в локальной базе —
    тоже возвращает существующий продукт, чтобы UI не дублировал.

    Payload: {"barcode": "..."}
    """
    barcode = (payload.get("barcode") or "").strip()
    if not barcode:
        raise HTTPException(400, "'barcode' is required")
    if not barcode.isdigit():
        raise HTTPException(400, "Штрих-код должен содержать только цифры")

    # Сначала локальный справочник
    existing = ingredients_store.find_by_barcode(barcode)
    if existing:
        return {
            "found": True,
            "local": True,
            "product": existing,
            "source": "local",
        }

    # Внутренний код магазина — сразу говорим, что не найдём
    if is_internal_barcode(barcode):
        return {
            "found": False,
            "local": False,
            "source": "internal_barcode",
            "message": "Весовой товар магазина. Введите название вручную.",
        }

    # OFF
    res = await fetch_product(barcode)
    return {
        "found": res.get("found", False),
        "local": False,
        "product": res.get("product"),
        "source": res.get("source"),
        "cached": res.get("cached", False),
    }


@router.post("/import-from-off")
async def import_from_off(payload: dict[str, Any] = Body(...)):
    """Сохраняет продукт, полученный ранее из OFF (после lookup).

    Payload — словарь продукта из ответа /lookup. Опционально можно
    переопределить поля из UI (name, brand, nutrition_per_100g).
    """
    barcode = (payload.get("barcode") or "").strip()
    if not barcode:
        raise HTTPException(400, "'barcode' is required")

    # Уже есть — обновим, а не создадим дубликат
    existing = ingredients_store.find_by_barcode(barcode)
    if existing:
        patch = {
            k: v
            for k, v in payload.items()
            if k in {
                "name", "brand", "category", "image_url",
                "nutrition_per_100g", "serving_size",
            } and v is not None
        }
        updated = await ingredients_store.update(existing["id"], patch)
        return {"product": updated, "created": False}

    product_data = {
        "id": off_product_id(barcode),
        "name": payload.get("name"),
        "brand": payload.get("brand"),
        "category": payload.get("category"),
        "barcode": barcode,
        "image_url": payload.get("image_url"),
        "nutrition_per_100g": payload.get("nutrition_per_100g") or {},
        "kind": "packaged",
        "default_unit": "г",
        "source": "openfoodfacts",
        "off_last_sync": payload.get("raw_last_modified"),
    }
    if not product_data["name"]:
        raise HTTPException(400, "'name' is required to save the product")

    product = await ingredients_store.add(product_data)
    return {"product": product, "created": True}


@router.post("/{product_id}/contribute")
async def contribute_to_off(product_id: str):
    """Отправляет продукт в Open Food Facts.

    Работает только если off_contribute_enabled=true и указаны
    off_user_id/off_password в настройках.
    """
    ok, reason = await can_contribute()
    if not ok:
        raise HTTPException(400, reason or "Contribution is not allowed")

    p = ingredients_store.get(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    if not p.get("barcode"):
        raise HTTPException(400, "Для отправки в OFF нужен штрих-код")

    result = await contribute_product(p)
    if not result.get("ok"):
        raise HTTPException(502, result.get("message") or "Contribution failed")
    return result


# --- Кэш ------------------------------------------------------------------

@router.get("/cache/stats")
async def get_cache_stats():
    return await cache_stats()


@router.delete("/cache")
async def clear_cache():
    n = await cache_clear()
    return {"cleared": n}