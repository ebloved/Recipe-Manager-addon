"""Роуты синхронизации с GitHub."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from services.github_sync import pull_recipes, push_recipes, status
from stores import recipe_store

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
async def sync_status():
    """Показывает настройки и состояние файла в GitHub."""
    try:
        return await status()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.post("/push")
async def sync_push(payload: dict[str, Any] = Body(default={})):
    """Заливает текущий recipes.json в GitHub."""
    content = json.dumps(
        {"recipes": recipe_store.recipes}, ensure_ascii=False, indent=2
    )
    message = payload.get("message") if isinstance(payload, dict) else None
    result = await push_recipes(content, message)
    return {"ok": True, **result}


@router.post("/pull")
async def sync_pull(payload: dict[str, Any] = Body(default={})):
    """Забирает recipes.json из GitHub и заменяет локальный.

    payload.replace_all=True  — полная замена (по умолчанию)
    payload.replace_all=False — объединение по id (локальные приоритетнее)
    """
    replace_all = True
    if isinstance(payload, dict) and payload.get("replace_all") is not None:
        replace_all = bool(payload.get("replace_all"))

    raw = await pull_recipes()
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Файл в GitHub не является корректным JSON: {exc}") from exc

    incoming = data.get("recipes") if isinstance(data, dict) else None
    if not isinstance(incoming, list):
        raise HTTPException(400, "Ожидался объект {'recipes': [...]}")

    if replace_all:
        recipe_store.recipes = incoming
        added = len(incoming)
    else:
        existing_ids = {r.get("id") for r in recipe_store.recipes if r.get("id")}
        added = 0
        for r in incoming:
            rid = r.get("id")
            if rid and rid in existing_ids:
                continue
            recipe_store.recipes.append(r)
            added += 1

    await recipe_store.save()
    return {
        "ok": True,
        "mode": "replace" if replace_all else "merge",
        "added": added,
        "total": len(recipe_store.recipes),
    }