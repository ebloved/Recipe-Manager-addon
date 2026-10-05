"""Хранилище списка покупок (JSON-файл)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import SHOPPING_FILE


class ShoppingStore:
    """Записи списка покупок.

    Формат записи:
        {
            id, name, amount, unit, brand, barcode, image_url,
            category, note, checked, recipe_id, recipe_name,
            source, created_at
        }
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.items = data.get("items", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[shopping] failed to load: {exc}")
            self.items = []

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(
                    json.dumps({"items": self.items}, ensure_ascii=False, indent=2)
                )
            tmp.replace(self.path)

    # --- queries ---------------------------------------------------------

    def get_all(self, only_active: bool = False) -> list[dict[str, Any]]:
        if only_active:
            return [i for i in self.items if not i.get("checked")]
        return list(self.items)

    def get(self, item_id: str) -> dict[str, Any] | None:
        return next((i for i in self.items if i.get("id") == item_id), None)

    def find_by_name(self, name: str) -> dict[str, Any] | None:
        """Поиск по имени без учёта регистра (для объединения дубликатов)."""
        needle = (name or "").strip().lower()
        if not needle:
            return None
        return next(
            (i for i in self.items if (i.get("name") or "").strip().lower() == needle),
            None,
        )

    # --- mutations -------------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex,
            "name": (data.get("name") or "").strip(),
            "amount": data.get("amount"),
            "unit": data.get("unit"),
            "brand": data.get("brand"),
            "barcode": data.get("barcode"),
            "image_url": data.get("image_url"),
            "category": data.get("category"),
            "note": data.get("note"),
            "checked": bool(data.get("checked", False)),
            "recipe_id": data.get("recipe_id"),
            "recipe_name": data.get("recipe_name"),
            "source": data.get("source") or "manual",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.items.append(item)
        await self.save()
        return item

    async def add_or_merge(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Если такой name уже есть — объединяет; иначе добавляет.

        Возвращает (item, merged).
        """
        existing = self.find_by_name(data.get("name") or "")
        if existing:
            new_note = self._merge_note(existing.get("note"), data.get("note"))
            patch: dict[str, Any] = {"checked": False}
            if new_note:
                patch["note"] = new_note
            # Если у старого нет amount/unit, а у нового есть — подтягиваем
            if not existing.get("amount") and data.get("amount"):
                patch["amount"] = data["amount"]
            if not existing.get("unit") and data.get("unit"):
                patch["unit"] = data["unit"]
            updated = await self.update(existing["id"], patch)
            return updated or existing, True
        item = await self.add(data)
        return item, False

    @staticmethod
    def _merge_note(old: str | None, new: str | None) -> str | None:
        old = (old or "").strip()
        new = (new or "").strip()
        if not new:
            return old or None
        if not old:
            return new
        if new in old:
            return old
        return f"{old}\n{new}"

    async def update(self, item_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "name", "amount", "unit", "brand", "barcode", "image_url",
            "category", "note", "checked", "recipe_id", "recipe_name", "source",
        }
        clean = {k: v for k, v in patch.items() if k in allowed}

        for i, item in enumerate(self.items):
            if item.get("id") == item_id:
                updated = {**item, **clean}
                self.items[i] = updated
                await self.save()
                return updated
        return None

    async def toggle(self, item_id: str) -> dict[str, Any] | None:
        item = self.get(item_id)
        if not item:
            return None
        return await self.update(item_id, {"checked": not item.get("checked", False)})

    async def delete(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i.get("id") != item_id]
        if len(self.items) < before:
            await self.save()
            return True
        return False

    async def clear_checked(self) -> int:
        before = len(self.items)
        self.items = [i for i in self.items if not i.get("checked")]
        removed = before - len(self.items)
        if removed:
            await self.save()
        return removed

    async def clear_all(self) -> int:
        count = len(self.items)
        self.items = []
        if count:
            await self.save()
        return count


shopping_store = ShoppingStore(SHOPPING_FILE)