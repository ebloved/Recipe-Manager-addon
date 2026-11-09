"""Хранилище предложенных LLM рецептов."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import SUGGESTIONS_FILE


class SuggestionsStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path = SUGGESTIONS_FILE) -> None:
        self.path = path
        self.suggestions: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.suggestions = data.get("suggestions", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[suggestions] failed to load: {exc}")
            self.suggestions = []
        print(f"[suggestions] loaded {len(self.suggestions)} suggestions")

    async def _save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "suggestions": self.suggestions,
            }
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def save(self) -> None:
        await self._save()

    @staticmethod
    def origin_of(suggestion: dict[str, Any]) -> str:
        return str(suggestion.get("origin") or "recipe")

    def get_all(
        self,
        status: str | None = "pending",
        *,
        origin: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(self.suggestions)
        if origin:
            items = [s for s in items if self.origin_of(s) == origin]
        if owner_id is not None:
            items = [
                s for s in items
                if not s.get("owner_id") or s.get("owner_id") == owner_id
            ]
        if status not in (None, "all"):
            items = [s for s in items if s.get("status") == status]
        return items

    def get_for_draft(self, draft_id: str) -> list[dict[str, Any]]:
        return [
            s for s in self.suggestions
            if s.get("origin") == "meal_plan" and s.get("draft_id") == draft_id
        ]

    def get(self, sid: str) -> dict[str, Any] | None:
        return next((s for s in self.suggestions if s.get("id") == sid), None)

    async def add_many(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.suggestions.extend(items)
        await self._save()
        return items

    async def update(self, sid: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        for i, s in enumerate(self.suggestions):
            if s.get("id") == sid:
                self.suggestions[i] = {**s, **patch}
                await self._save()
                return self.suggestions[i]
        return None

    async def delete(self, sid: str) -> bool:
        before = len(self.suggestions)
        self.suggestions = [s for s in self.suggestions if s.get("id") != sid]
        if len(self.suggestions) < before:
            await self._save()
            return True
        return False


suggestions_store = SuggestionsStore()
