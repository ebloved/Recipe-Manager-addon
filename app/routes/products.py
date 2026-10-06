"""CRUD продуктов (база ингредиентов).

Эндпоинты:
    GET    /api/products                        — список (фильтр + пагинация)
    GET    /api/products/stats                  — статистика базы
    GET    /api/products/export                 — полный экспорт (для синка)
    GET    /api/products/search                 — быстрый поиск для UI
    GET    /api/products/{product_id}           — один продукт
    POST   /api/products                        — создать
    PATCH  /api/products/{product_id}           — обновить
    DELETE /api/products/{product_id}           — мягкое/жёсткое удаление
    POST   /api/products/{product_id}/restore   — восстановить
    POST   /api/products/{product_id}/alias     — добавить алиас
    DELETE /api/products/{product_id}/alias     — убрать алиас
    POST   /api/products/{product_id}/vector    — сохранить вектор
    POST   /api/products/merge                  — мерж входящего ingredients.json
    POST   /api/products/bulk-delete            — массовое мягкое удаление
    POST   /api/products/bulk-restore           — массовое восстановление

После каждой мутации инвалидируется кэш матчинга (cascade), чтобы
результаты match_name не были устаревшими.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from stores import ingredients_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])

_DEFAULT_LIST_LIMIT = 500


# ---------------------------------------------------------------------------
# Инвалидация кэша матчинга
# ---------------------------------------------------------------------------

async def _invalidate_matcher_cache() -> None:
    """Сбрасывает кэш каскада матчинга после изменений в базе продуктов.

    Если модуль матчинга ещё не собран или импорт упал — тихо пропускаем.
    Это позволяет использовать products CRUD независимо от matcher.
    """
    try:
        from services.matcher.cascade import invalidate_cache  # type: ignore[import]
        invalidate_cache()
    except Exception as exc:  # noqa: BLE001
        logger.debug("invalidate_cache недоступен: %s", exc)


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

@router.get("")
async def list_products(
    q: str | None = Query(default=None, description="Поиск по имени / бренду / barcode"),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
):
    """Возвращает список продуктов с необязательным поиском и пагинацией."""
    items = ingredients_store.list_all(include_deleted=include_deleted)

    if q:
        needle = q.strip().lower().replace("ё", "е")
        filtered = []
        for p in items:
            name = (p.get("name") or "").lower().replace("ё", "е")
            brand = (p.get("brand") or "").lower().replace("ё", "е")
            barcode = str(p.get("barcode") or "")
            aliases = [(a or "").lower().replace("ё", "е") for a in (p.get("aliases") or [])]

            if (needle in name
                or needle in brand
                or needle in barcode
                or any(needle in a for a in aliases)):
                filtered.append(p)
        items = filtered

    total = len(items)
    page = items[offset: offset + limit]

    return {
        "products": page,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/stats")
async def products_stats():
    """Краткая статистика по базе."""
    active = ingredients_store.list_all()
    all_products = ingredients_store.list_all(include_deleted=True)
    with_barcode = sum(1 for p in active if p.get("barcode"))
    with_nutrition = sum(1 for p in active if p.get("nutrition_per_100g"))
    with_vector = sum(1 for p in active if p.get("vectors"))
    return {
        "active": len(active),
        "deleted": len(all_products) - len(active),
        "with_barcode": with_barcode,
        "with_nutrition": with_nutrition,
        "with_vector": with_vector,
        "installation_id": ingredients_store.installation_id,
        "schema_version": ingredients_store.schema_version,
    }


@router.get("/export")
async def export_products():
    """Полный экспорт ingredients.json (для синка / бэкапа)."""
    return ingredients_store.export()


@router.get("/search")
async def search_products(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Быстрый поиск для UI: имя, алиас, barcode.

    Возвращает короткие объекты (без векторов) для отображения в списке.
    """
    needle = q.strip().lower().replace("ё", "е")

    def score(p: dict[str, Any]) -> int:
        name = (p.get("name") or "").lower().replace("ё", "е")
        if name == needle:
            return 0
        if name.startswith(needle):
            return 1
        if needle in name:
            return 2
        brand = (p.get("brand") or "").lower().replace("ё", "е")
        if needle in brand:
            return 3
        if needle == str(p.get("barcode") or ""):
            return 0
        for a in (p.get("aliases") or []):
            a_norm = (a or "").lower().replace("ё", "е")
            if a_norm == needle:
                return 0
            if needle in a_norm:
                return 4
        return 99

    candidates = []
    for p in ingredients_store.list_all():
        s = score(p)
        if s < 99:
            candidates.append((s, p))

    candidates.sort(key=lambda x: (x[0], x[1].get("name") or ""))
    sliced = [p for _, p in candidates[:limit]]

    return {"products": [_public_view(p) for p in sliced], "count": len(sliced)}


@router.get("/{product_id}")
async def get_product(product_id: str, include_deleted: bool = False):
    """Возвращает продукт по product_id."""
    p = ingredients_store.get(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    if p.get("deleted") and not include_deleted:
        raise HTTPException(404, "Product deleted")
    return {"product": p}


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------

@router.post("")
async def create_product(payload: dict[str, Any] = Body(...)):
    """Создаёт новый продукт.

    Обязательные поля: name.
    Опциональные: barcode, brand, image_url, category, source,
                  nutrition_per_100g, serving_size_g, aliases.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")

    # Проверка: не занят ли barcode
    barcode = payload.get("barcode")
    if barcode:
        existing = ingredients_store.get_by_barcode(str(barcode))
        if existing:
            raise HTTPException(
                409,
                f"Продукт с barcode {barcode} уже существует: "
                f"'{existing.get('name')}' ({existing.get('product_id')})",
            )

    # Проверка: не занято ли имя (с учётом алиасов)
    existing_name = ingredients_store.find_by_name(name)
    if existing_name:
        raise HTTPException(
            409,
            f"Продукт с именем '{name}' уже существует: "
            f"'{existing_name.get('name')}' ({existing_name.get('product_id')})",
        )

    try:
        product = await ingredients_store.add(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    await _invalidate_matcher_cache()
    return {"product": product}


@router.patch("/{product_id}")
async def update_product(product_id: str, patch: dict[str, Any] = Body(...)):
    """Обновляет продукт. Меняет только разрешённые поля."""
    existing = ingredients_store.get(product_id)
    if not existing:
        raise HTTPException(404, "Product not found")

    # Проверка barcode на конфликт
    new_barcode = patch.get("barcode")
    if new_barcode and str(new_barcode) != (existing.get("barcode") or ""):
        clash = ingredients_store.get_by_barcode(str(new_barcode))
        if clash and clash.get("product_id") != product_id:
            raise HTTPException(
                409,
                f"Barcode {new_barcode} уже принадлежит продукту '{clash.get('name')}'",
            )

    try:
        updated = await ingredients_store.update(product_id, patch)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not updated:
        raise HTTPException(404, "Product not found")

    # Инвалидируем кэш: name/aliases/barcode могли измениться
    await _invalidate_matcher_cache()
    return {"product": updated}


@router.delete("/{product_id}")
async def delete_product(product_id: str, hard: bool = False):
    """Мягкое удаление (по умолчанию) или жёсткое (?hard=true)."""
    ok = await ingredients_store.delete(product_id, soft=not hard)
    if not ok:
        raise HTTPException(404, "Product not found")
    await _invalidate_matcher_cache()
    return {"deleted": True, "hard": hard}


@router.post("/{product_id}/restore")
async def restore_product(product_id: str):
    """Восстанавливает мягко удалённый продукт."""
    restored = await ingredients_store.restore(product_id)
    if not restored:
        raise HTTPException(404, "Product not found")
    await _invalidate_matcher_cache()
    return {"product": restored}


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

@router.post("/{product_id}/alias")
async def add_alias(product_id: str, payload: dict[str, Any] = Body(...)):
    """Добавляет алиас к продукту. Payload: {alias: '...'}."""
    alias = (payload.get("alias") or "").strip()
    if not alias:
        raise HTTPException(400, "'alias' is required")
    try:
        product = await ingredients_store.add_alias(product_id, alias)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not product:
        raise HTTPException(404, "Product not found")
    await _invalidate_matcher_cache()
    return {"product": product}


@router.delete("/{product_id}/alias")
async def remove_alias(product_id: str, payload: dict[str, Any] = Body(...)):
    """Удаляет алиас. Payload: {alias: '...'}."""
    alias = (payload.get("alias") or "").strip()
    if not alias:
        raise HTTPException(400, "'alias' is required")
    product = await ingredients_store.remove_alias(product_id, alias)
    if not product:
        raise HTTPException(404, "Product not found")
    await _invalidate_matcher_cache()
    return {"product": product}


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------

@router.post("/{product_id}/vector")
async def set_vector(product_id: str, payload: dict[str, Any] = Body(...)):
    """Сохраняет вектор эмбеддинга для продукта.

    Payload: {model_key: 'gemini:gemini-embedding-001:768', vector: [...]}
    """
    model_key = (payload.get("model_key") or "").strip()
    vector = payload.get("vector")
    if not model_key:
        raise HTTPException(400, "'model_key' is required")
    if not isinstance(vector, list) or not vector:
        raise HTTPException(400, "'vector' must be a non-empty list")

    if not ingredients_store.get(product_id):
        raise HTTPException(404, "Product not found")

    await ingredients_store.set_vector(product_id, model_key, vector)
    # Вектор продукта изменился — кэш матчинга тоже невалиден
    await _invalidate_matcher_cache()
    return {"ok": True, "model_key": model_key, "dim": len(vector)}


# ---------------------------------------------------------------------------
# Merge (для синхронизации с GitHub)
# ---------------------------------------------------------------------------

@router.post("/merge")
async def merge_products(payload: dict[str, Any] = Body(...)):
    """Мержит входящий ingredients.json в текущую базу.

    Payload:
        data: объект файла ingredients.json (с ключами products, schema_version, ...)
        strategy: 'last-write-wins' | 'local-wins' | 'remote-wins'
                  (по умолчанию 'last-write-wins')

    Возвращает статистику мержа.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(400, "'data' must be an object")
    if not isinstance(data.get("products"), list):
        raise HTTPException(400, "'data.products' must be a list")

    strategy = payload.get("strategy") or "last-write-wins"
    if strategy not in ("last-write-wins", "local-wins", "remote-wins"):
        raise HTTPException(400, f"Unknown strategy: {strategy}")

    stats = ingredients_store.merge_from(data, strategy=strategy)
    await ingredients_store.save()

    await _invalidate_matcher_cache()
    return {"ok": True, "strategy": strategy, "stats": stats}


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

@router.post("/bulk-delete")
async def bulk_delete(payload: dict[str, Any] = Body(...)):
    """Массовое мягкое удаление продуктов.

    Payload:
        product_ids: list[str]
        hard: bool = false   — жёсткое удаление без возможности restore

    Возвращает количество удалённых и не найденных.
    """
    ids = payload.get("product_ids") or []
    if not isinstance(ids, list):
        raise HTTPException(400, "'product_ids' must be a list")
    hard = bool(payload.get("hard", False))

    deleted = 0
    missing = 0
    for pid in ids:
        if not isinstance(pid, str) or not pid:
            continue
        ok = await ingredients_store.delete(pid, soft=not hard)
        if ok:
            deleted += 1
        else:
            missing += 1

    if deleted:
        await _invalidate_matcher_cache()

    return {"deleted": deleted, "missing": missing, "hard": hard}


@router.post("/bulk-restore")
async def bulk_restore(payload: dict[str, Any] = Body(...)):
    """Массовое восстановление мягко удалённых продуктов.

    Payload:
        product_ids: list[str]
    """
    ids = payload.get("product_ids") or []
    if not isinstance(ids, list):
        raise HTTPException(400, "'product_ids' must be a list")

    restored = 0
    missing = 0
    for pid in ids:
        if not isinstance(pid, str) or not pid:
            continue
        r = await ingredients_store.restore(pid)
        if r:
            restored += 1
        else:
            missing += 1

    if restored:
        await _invalidate_matcher_cache()

    return {"restored": restored, "missing": missing}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _public_view(p: dict[str, Any]) -> dict[str, Any]:
    """Короткое представление продукта для UI-списков (без векторов)."""
    return {
        "product_id": p.get("product_id"),
        "name": p.get("name"),
        "brand": p.get("brand"),
        "barcode": p.get("barcode"),
        "image_url": p.get("image_url"),
        "category": p.get("category"),
        "nutrition_per_100g": p.get("nutrition_per_100g"),
        "serving_size_g": p.get("serving_size_g"),
        "aliases": p.get("aliases") or [],
        "source": p.get("source"),
        "updated_at": p.get("updated_at"),
    }