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


    def _migrate(self):
        """Присваивает 'family' старым записям без owner_id."""
        changed = False
        items = getattr(self, "items", getattr(self, "entries", []))
        for item in items:
            if "owner_id" not in item:
                item["owner_id"] = "family"
                changed = True
        return changed

    @staticmethod
    def _notify_webhooks(owner_id: str | None) -> None:
        if not owner_id:
            return
        try:
            from services.webhooks import webhook_manager
            webhook_manager.schedule(owner_id, event="meal_plan")
        except Exception as exc:  # noqa: BLE001
            print(f"[webhook] schedule failed: {type(exc).__name__}: {exc}")

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.entries = data.get("entries", [])
            if self._migrate():
                await self.save()
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

    async def add(self, data: dict[str, Any], owner_id: str) -> dict[str, Any]:
        entry = {
            "id": uuid.uuid4().hex,
            "owner_id": owner_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self.entries.append(entry)
        await self.save()
        self._notify_webhooks(owner_id)
        return entry

    async def add_many(
        self,
        items: list[dict[str, Any]],
        owner_id: str,
    ) -> list[dict[str, Any]]:
        """Добавляет несколько записей одним сохранением файла."""
        if not items:
            return []
        now = datetime.now(timezone.utc).isoformat()
        entries = [
            {"id": uuid.uuid4().hex, "owner_id": owner_id, "created_at": now, **data}
            for data in items
        ]
        before = len(self.entries)
        self.entries.extend(entries)
        try:
            await self.save()
        except Exception:
            del self.entries[before:]
            raise
        self._notify_webhooks(owner_id)
        return entries

    async def update(self, entry_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        for i, e in enumerate(self.entries):
            if e.get("id") == entry_id:
                updated = {**e, **patch}
                self.entries[i] = updated
                await self.save()
                self._notify_webhooks(updated.get("owner_id"))
                return updated
        return None

    async def delete(self, entry_id: str) -> bool:
        removed = [e for e in self.entries if e.get("id") == entry_id]
        if not removed:
            return False
        self.entries = [e for e in self.entries if e.get("id") != entry_id]
        await self.save()
        for owner_id in {e.get("owner_id") for e in removed}:
            self._notify_webhooks(owner_id)
        return True

    async def delete_by_recipe(self, recipe_id: str) -> int:
        removed = [
            e for e in self.entries
            if e.get("recipe_id") == recipe_id or e.get("side_for") == recipe_id
        ]
        self.entries = [
            e for e in self.entries
            if e.get("recipe_id") != recipe_id and e.get("side_for") != recipe_id
        ]
        if removed:
            await self.save()
            for owner_id in {e.get("owner_id") for e in removed}:
                self._notify_webhooks(owner_id)
        return len(removed)


meal_plan_store = MealPlanStore(MEAL_PLAN_FILE)