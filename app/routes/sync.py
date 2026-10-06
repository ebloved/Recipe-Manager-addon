"""Роуты синхронизации с GitHub.

Синхронизирует ДВА файла одним коммитом:
  - recipes.json      (рецепты)
  - ingredients.json  (база продуктов и связок)

Эндпоинты:
    GET  /api/sync/status   — настройки и состояние обоих файлов в GitHub
    POST /api/sync/push     — залить оба файла одним коммитом
    POST /api/sync/pull     — забрать оба файла и применить локально
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from services.github_sync import pull_one, push_many, status as gh_status
from stores import ingredients_store, recipe_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status")
async def sync_status():
    """Показывает настройки и состояние обоих файлов в GitHub."""
    try:
        return await gh_status()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

@router.post("/push")
async def sync_push(payload: dict[str, Any] = Body(default={})):
    """Заливает recipes.json и ingredients.json одним коммитом.

    Payload (опционально):
        message: str      — сообщение коммита
        what: str         — "all" (по умолчанию) | "recipes" | "ingredients"
    """
    what = (payload.get("what") or "all").lower() if isinstance(payload, dict) else "all"
    message = payload.get("message") if isinstance(payload, dict) else None

    files: dict[str, str] = {}

    if what in ("all", "recipes"):
        files["recipes.json"] = json.dumps(
            {"recipes": recipe_store.recipes}, ensure_ascii=False, indent=2
        )

    if what in ("all", "ingredients"):
        files["ingredients.json"] = json.dumps(
            ingredients_store.export(), ensure_ascii=False, indent=2
        )

    if not files:
        raise HTTPException(400, f"Нечего заливать (what='{what}')")

    try:
        result = await push_many(files, message=message)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc

    logger.info(
        "Sync push: %d файлов, commit=%s",
        len(files), (result.get("commit_sha") or "?")[:7],
    )
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

@router.post("/pull")
async def sync_pull(payload: dict[str, Any] = Body(default={})):
    """Забирает recipes.json и ingredients.json и применяет локально.

    Payload (опционально):
        what: str             — "all" (по умолчанию) | "recipes" | "ingredients"
        replace_all: bool     — только для recipes.
                                true  → полная замена (по умолчанию)
                                false → merge по id (локальные приоритетнее)
        merge_strategy: str   — только для ingredients.
                                'last-write-wins' | 'local-wins' | 'remote-wins'
                                (по умолчанию 'last-write-wins')
    """
    what = (payload.get("what") or "all").lower() if isinstance(payload, dict) else "all"
    replace_all = True
    if isinstance(payload, dict) and payload.get("replace_all") is not None:
        replace_all = bool(payload.get("replace_all"))

    merge_strategy = "last-write-wins"
    if isinstance(payload, dict) and payload.get("merge_strategy"):
        ms = str(payload["merge_strategy"])
        if ms not in ("last-write-wins", "local-wins", "remote-wins"):
            raise HTTPException(400, f"Unknown merge_strategy: {ms}")
        merge_strategy = ms

    result: dict[str, Any] = {"ok": True, "what": what}

    # --- Recipes ---
    if what in ("all", "recipes"):
        try:
            raw = await pull_one("recipes.json")
        except HTTPException as exc:
            # Файла нет в репе — не считаем это фатальной ошибкой
            if exc.status_code == 404:
                result["recipes"] = {"skipped": True, "reason": "not found in repo"}
            else:
                raise

        else:
            try:
                data = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, f"recipes.json не является валидным JSON: {exc}") from exc

            incoming = data.get("recipes") if isinstance(data, dict) else None
            if not isinstance(incoming, list):
                raise HTTPException(400, "Ожидался объект {'recipes': [...]} в recipes.json")

            if replace_all:
                recipe_store.recipes = incoming
                added = len(incoming)
                removed = 0
            else:
                existing_ids = {r.get("id") for r in recipe_store.recipes if r.get("id")}
                added = 0
                for r in incoming:
                    rid = r.get("id")
                    if rid and rid in existing_ids:
                        continue
                    recipe_store.recipes.append(r)
                    added += 1
                removed = 0

            await recipe_store.save()
            result["recipes"] = {
                "mode": "replace" if replace_all else "merge",
                "added": added,
                "removed": removed,
                "total": len(recipe_store.recipes),
            }

    # --- Ingredients ---
    if what in ("all", "ingredients"):
        try:
            raw = await pull_one("ingredients.json")
        except HTTPException as exc:
            if exc.status_code == 404:
                result["ingredients"] = {"skipped": True, "reason": "not found in repo"}
            else:
                raise

        else:
            try:
                data = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, f"ingredients.json не является валидным JSON: {exc}") from exc

            if not isinstance(data, dict) or not isinstance(data.get("products"), list):
                raise HTTPException(400, "Ожидался объект {'products': [...]} в ingredients.json")

            stats = ingredients_store.merge_from(data, strategy=merge_strategy)
            await ingredients_store.save()

            # Инвалидируем кэш матчинга — база продуктов изменилась
            try:
                from services.matcher.cascade import invalidate_cache  # type: ignore[import]
                invalidate_cache()
            except Exception:  # noqa: BLE001
                pass

            result["ingredients"] = {
                "strategy": merge_strategy,
                "total": ingredients_store.count(),
                "stats": stats,
            }

    return result