"""Хранилище рецептов (JSON-файл)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import RECIPES_FILE


class RecipeStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.recipes: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.recipes = data.get("recipes", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[recipes] failed to load: {exc}")
            self.recipes = []

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(
                    json.dumps({"recipes": self.recipes}, ensure_ascii=False, indent=2)
                )
            tmp.replace(self.path)

    def get_all(self) -> list[dict[str, Any]]:
        return list(self.recipes)

    def get(self, recipe_id: str) -> dict[str, Any] | None:
        return next((r for r in self.recipes if r.get("id") == recipe_id), None)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        recipe = {"id": uuid.uuid4().hex, "created_at": now, "updated_at": now, **data}
        self.recipes.append(recipe)
        await self.save()
        return recipe

    async def update(self, recipe_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        for i, r in enumerate(self.recipes):
            if r.get("id") == recipe_id:
                updated = {
                    **r,
                    **patch,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.recipes[i] = updated
                await self.save()
                return updated
        return None

    async def delete(self, recipe_id: str) -> bool:
        before = len(self.recipes)
        self.recipes = [r for r in self.recipes if r.get("id") != recipe_id]
        if len(self.recipes) < before:
            await self.save()
            return True
        return False

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for r in self.recipes:
            for t in r.get("tags") or []:
                if isinstance(t, str) and t.strip():
                    tags.add(t.strip())
        return sorted(tags)


recipe_store = RecipeStore(RECIPES_FILE)