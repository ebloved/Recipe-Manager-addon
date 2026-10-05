"""Хранилище плана питания (JSON-файл)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import MEAL_PLAN_FILE


class MealPlanStore:
    """Записи плана: {id, recipe_id, date, meal_type, servings, notes}."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.entries = data.get("entries", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[meal-plan] failed to load: {exc}")
            self.entries = []

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(
                    json.dumps({"entries": self.entries}, ensure_ascii=False, indent=2)
                )
            tmp.replace(self.path)

    def get_range(self, start: str, end: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if start <= (e.get("date") or "") <= end]

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return next((e for e in self.entries if e.get("id") == entry_id), None)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self.entries.append(entry)
        await self.save()
        return entry

    async def update(self, entry_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        for i, e in enumerate(self.entries):
            if e.get("id") == entry_id:
                updated = {**e, **patch}
                self.entries[i] = updated
                await self.save()
                return updated
        return None

    async def delete(self, entry_id: str) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.get("id") != entry_id]
        if len(self.entries) < before:
            await self.save()
            return True
        return False

    async def delete_by_recipe(self, recipe_id: str) -> int:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.get("recipe_id") != recipe_id]
        removed = before - len(self.entries)
        if removed:
            await self.save()
        return removed


meal_plan_store = MealPlanStore(MEAL_PLAN_FILE)