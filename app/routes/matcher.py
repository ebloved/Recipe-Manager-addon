"""Эндпоинты матчинга ингредиентов с продуктами.

Здесь только HTTP-обвязка. Логика каскада живёт в `services/matcher/`.

Эндпоинты:
    POST   /api/matcher/match                — матч одного имени
    POST   /api/matcher/match-batch          — матч массива имён
    POST   /api/matcher/validate             — генеративная валидация пары (name, product_id)
    POST   /api/matcher/confirm              — подтвердить связку (записать алиас)
    GET    /api/matcher/status               — состояние каскада (провайдеры, лимиты)
    POST   /api/matcher/provider-check       — проверить доступность провайдера
    POST   /api/matcher/apply-to-recipe      — применить связки к рецепту
    GET    /api/matcher/queue                — очередь отложенных подтверждений
    POST   /api/matcher/queue/clear          — очистить очередь
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from stores import ingredients_store

router = APIRouter(prefix="/api/matcher", tags=["matcher"])


# ---------------------------------------------------------------------------
# Импорт сервиса с graceful degradation.
# Пока пакет app/services/matcher/ не собран, эндпоинты вернут 503
# с понятным сообщением. Это позволяет собрать фронтенд и остальную часть
# бэкенда до того, как каскад будет полностью реализован.
# ---------------------------------------------------------------------------

try:
    from services import matcher as matcher_service  # type: ignore[import]
    _MATCHER_AVAILABLE = True
    _MATCHER_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    matcher_service = None  # type: ignore[assignment]
    _MATCHER_AVAILABLE = False
    _MATCHER_IMPORT_ERROR = str(exc)


def _require_matcher() -> None:
    if not _MATCHER_AVAILABLE:
        raise HTTPException(
            503,
            "Модуль матчинга ещё не собран в этой сборке аддона. "
            f"Внутренняя ошибка импорта: {_MATCHER_IMPORT_ERROR}",
        )


# ---------------------------------------------------------------------------
# Очередь отложенных подтверждений (in-memory).
# Используется в batch-режиме, когда пользователь импортирует сразу
# много рецептов и подтверждения нужно накопить и показать один раз.
# ---------------------------------------------------------------------------

_PENDING_QUEUE: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------

@router.post("/match")
async def match_single(payload: dict[str, Any] = Body(...)):
    """Матч одного имени ингредиента.

    Payload:
        name: str
        context: dict | None  — необязательный контекст
                                 (например, {recipe_name: '...'})
        thresholds: dict | None  — переопределить пороги
                                   {auto: 0.95, suggest: 0.80}

    Returns:
        {
            "query": "<name>",
            "match": {
                "product_id": ...,
                "name": ...,
                "score": 0.94,
                "method": "exact" | "alias" | "fuzzy" | "vector" | "generative",
                "provider": "local" | "gemini" | "hermes" | ...
            } | null,
            "needs_confirmation": bool,
            "candidates": [ {...}, ... ]
        }
    """
    _require_matcher()

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")

    result = await matcher_service.match_name(
        name=name,
        context=payload.get("context") or None,
        thresholds=payload.get("thresholds") or None,
    )
    return result


@router.post("/match-batch")
async def match_batch(payload: dict[str, Any] = Body(...)):
    """Матч массива имён.

    Payload:
        names: list[str]
        context: dict | None
        thresholds: dict | None
        deduplicate: bool = true   — схлопывать одинаковые имена
        queue_pending: bool = false — складывать спорные в очередь
                                       вместо возврата

    Returns:
        {
            "results": [ { ...см. /match... } ],
            "stats": {
                "total": 120,
                "unique": 87,
                "matched_auto": 55,
                "need_confirmation": 20,
                "not_found": 12,
            }
        }
    """
    _require_matcher()

    names = payload.get("names") or []
    if not isinstance(names, list):
        raise HTTPException(400, "'names' must be a list")

    clean_names: list[str] = []
    for n in names:
        if isinstance(n, str) and n.strip():
            clean_names.append(n.strip())

    if not clean_names:
        return {"results": [], "stats": {
            "total": 0, "unique": 0, "matched_auto": 0,
            "need_confirmation": 0, "not_found": 0,
        }}

    deduplicate = bool(payload.get("deduplicate", True))
    queue_pending = bool(payload.get("queue_pending", False))

    result = await matcher_service.match_batch(
        names=clean_names,
        context=payload.get("context") or None,
        thresholds=payload.get("thresholds") or None,
        deduplicate=deduplicate,
    )

    if queue_pending:
        for r in result.get("results", []):
            if r.get("needs_confirmation") and r.get("candidates"):
                _PENDING_QUEUE.append(r)

    return result


@router.post("/validate")
async def validate_pair(payload: dict[str, Any] = Body(...)):
    """Генеративная валидация пары «имя ингредиента» / «продукт».

    Вызывается, когда векторное сходство дало спорный score
    (в диапазоне suggest..auto). Спрашиваем LLM: «Это один продукт?».

    Payload:
        name: str
        product_id: str

    Returns:
        {
            "valid": true | false | null,
            "provider": "hermes" | "gemini" | null,
            "confidence": 0.0..1.0 | null,
            "reason": "..." | null
        }
    """
    _require_matcher()

    name = (payload.get("name") or "").strip()
    product_id = (payload.get("product_id") or "").strip()
    if not name or not product_id:
        raise HTTPException(400, "'name' and 'product_id' are required")

    product = ingredients_store.get_active(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    return await matcher_service.validate_pair(name=name, product=product)


@router.post("/confirm")
async def confirm_link(payload: dict[str, Any] = Body(...)):
    """Подтверждает связку «имя → продукт», записывая имя как алиас.

    Payload:
        name: str
        product_id: str
        add_alias: bool = true  — добавлять ли имя как алиас
        apply_to_recipe_id: str | None — заодно проставить product_id
                                          во все ингредиенты рецепта с этим именем

    Returns:
        {
            "ok": true,
            "product": {...},
            "recipe_updated": bool
        }
    """
    _require_matcher()

    name = (payload.get("name") or "").strip()
    product_id = (payload.get("product_id") or "").strip()
    if not name or not product_id:
        raise HTTPException(400, "'name' and 'product_id' are required")

    product = ingredients_store.get_active(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    add_alias = bool(payload.get("add_alias", True))
    if add_alias:
        try:
            product = await ingredients_store.add_alias(product_id, name) or product
        except ValueError as exc:
            # алиас занят другим продуктом — это не критично, но сообщим
            raise HTTPException(409, str(exc)) from exc

    recipe_updated = False
    recipe_id = payload.get("apply_to_recipe_id")
    if recipe_id:
        try:
            recipe_updated = await matcher_service.apply_link_to_recipe(
                recipe_id=recipe_id,
                ingredient_name=name,
                product_id=product_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Не удалось обновить рецепт: {exc}") from exc

    # Убираем из очереди, если была
    _remove_from_queue(name)

    return {
        "ok": True,
        "product": product,
        "recipe_updated": recipe_updated,
    }


@router.post("/apply-to-recipe")
async def apply_to_recipe(payload: dict[str, Any] = Body(...)):
    """Применяет уже подтверждённые связки к рецепту (массово).

    Полезно после импорта: пользователь подтвердил 15 связок,
    теперь применяем их ко всем ингредиентам рецепта.

    Payload:
        recipe_id: str
        links: list[{name, product_id}]
    """
    _require_matcher()

    recipe_id = (payload.get("recipe_id") or "").strip()
    links = payload.get("links") or []
    if not recipe_id or not isinstance(links, list):
        raise HTTPException(400, "'recipe_id' and 'links' are required")

    updated = await matcher_service.apply_links_to_recipe(
        recipe_id=recipe_id,
        links=links,
    )
    return {"ok": True, "updated": updated}


# ---------------------------------------------------------------------------
# Status / provider check
# ---------------------------------------------------------------------------

@router.get("/status")
async def matcher_status():
    """Возвращает состояние каскада: доступные провайдеры, приоритеты, лимиты."""
    if not _MATCHER_AVAILABLE:
        return {
            "available": False,
            "error": _MATCHER_IMPORT_ERROR,
            "providers": [],
            "priority": [],
        }

    try:
        info = await matcher_service.status()
        return {"available": True, **info}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Ошибка получения статуса: {exc}") from exc


@router.post("/provider-check")
async def provider_check(payload: dict[str, Any] = Body(...)):
    """Проверяет доступность конкретного провайдера.

    Payload:
        provider: 'hermes' | 'gemini' | 'local' | 'openrouter' | 'groq'

    Returns:
        {
            "provider": "...",
            "ok": true | false,
            "latency_ms": 123 | null,
            "detail": "..." | null
        }
    """
    _require_matcher()

    provider = (payload.get("provider") or "").strip().lower()
    if not provider:
        raise HTTPException(400, "'provider' is required")

    return await matcher_service.check_provider(provider)


# ---------------------------------------------------------------------------
# Queue (batch confirm)
# ---------------------------------------------------------------------------

@router.get("/queue")
async def get_queue():
    """Возвращает очередь отложенных подтверждений."""
    return {
        "count": len(_PENDING_QUEUE),
        "items": list(_PENDING_QUEUE),
    }


@router.post("/queue/remove")
async def remove_from_queue(payload: dict[str, Any] = Body(...)):
    """Убирает элемент из очереди по имени или query.

    Payload:
        query: str
    """
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "'query' is required")

    removed = _remove_from_queue(query)
    return {"removed": removed}


@router.post("/queue/clear")
async def clear_queue():
    """Полностью очищает очередь."""
    n = len(_PENDING_QUEUE)
    _PENDING_QUEUE.clear()
    return {"cleared": n}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _remove_from_queue(query: str) -> bool:
    """Убирает из очереди запись с таким query. Возвращает True если что-то убрали."""
    global _PENDING_QUEUE
    before = len(_PENDING_QUEUE)
    _PENDING_QUEUE = [
        item for item in _PENDING_QUEUE
        if (item.get("query") or "").strip().lower() != query.strip().lower()
    ]
    return len(_PENDING_QUEUE) < before