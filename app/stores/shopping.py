"""Хранилище списка покупок (SQLite + in-memory read cache).

SQLite — источник истины. Кеш нужен потому, что часть роутов
(например, export-for-connector) читает список синхронно.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from db import SessionLocal
from stores.db_models import ShoppingItem


class ShoppingStore:
    """Записи списка покупок.

    Формат записи:
        {
            id, name, amount, unit, brand, barcode, image_url,
            category, note, checked, recipe_id, recipe_name,
            source, product_id, owner_id, created_at
        }
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    # --- db helpers ------------------------------------------------------

    @staticmethod
    def _to_dict(row: ShoppingItem) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "amount": row.amount,
            "unit": row.unit,
            "brand": row.brand,
            "barcode": row.barcode,
            "image_url": row.image_url,
            "category": row.category,
            "note": row.note,
            "checked": bool(row.checked),
            "recipe_id": row.recipe_id,
            "recipe_name": row.recipe_name,
            "source": row.source,
            "product_id": row.product_id,
            "owner_id": row.owner_id,
            "created_at": row.created_at,
        }

    def _cache_update(self, item: dict[str, Any]) -> None:
        for idx, existing in enumerate(self.items):
            if existing.get("id") == item.get("id"):
                self.items[idx] = item
                return
        self.items.append(item)

    def _cache_remove(self, item_id: str) -> None:
        self.items = [i for i in self.items if i.get("id") != item_id]

    # --- lifecycle -------------------------------------------------------

    async def load(self) -> None:
        try:
            async with SessionLocal() as session:
                result = await session.execute(
                    select(ShoppingItem)
                    .where(ShoppingItem.deleted_at.is_(None))
                    .order_by(ShoppingItem.created_at)
                )
                rows = result.scalars().all()
            self.items = [self._to_dict(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            print(f"[shopping] failed to load from SQLite: {exc}")
            self.items = []

    async def save(self) -> None:
        """Совместимость со старым API. SQLite пишется в методах мутации."""
        return None

    # --- queries ---------------------------------------------------------

    def get_all(self, owner_id: str, only_active: bool = False) -> list[dict[str, Any]]:
        if only_active:
            return [
                i for i in self.items
                if i.get("owner_id") == owner_id and not i.get("checked")
            ]
        return [i for i in self.items if i.get("owner_id") == owner_id]

    def get(self, item_id: str) -> dict[str, Any] | None:
        return next((i for i in self.items if i.get("id") == item_id), None)

    def find_by_name(self, name: str, owner_id: str) -> dict[str, Any] | None:
        """Поиск по имени без учёта регистра (для объединения дубликатов)."""
        needle = (name or "").strip().lower()
        if not needle:
            return None
        return next(
            (
                i for i in self.items
                if (i.get("name") or "").strip().lower() == needle
                and i.get("owner_id") == owner_id
            ),
            None,
        )

    # --- mutations -------------------------------------------------------

    async def add(self, data: dict[str, Any], owner_id: str) -> dict[str, Any]:
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
            "product_id": data.get("product_id"),
            "owner_id": owner_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        async with SessionLocal() as session:
            session.add(
                ShoppingItem(
                    id=item["id"],
                    owner_id=item["owner_id"],
                    name=item["name"],
                    amount=item["amount"],
                    unit=item["unit"],
                    brand=item["brand"],
                    barcode=item["barcode"],
                    image_url=item["image_url"],
                    category=item["category"],
                    note=item["note"],
                    checked=item["checked"],
                    recipe_id=item["recipe_id"],
                    recipe_name=item["recipe_name"],
                    source=item["source"],
                    product_id=item["product_id"],
                    created_at=item["created_at"],
                )
            )
            await session.commit()
        self._cache_update(item)
        return item

    async def add_or_merge(self, data: dict[str, Any], owner_id: str) -> tuple[dict[str, Any], bool]:
        """Если такой name уже есть — объединяет; иначе добавляет.

        Возвращает (item, merged).
        """
        existing = self.find_by_name(data.get("name") or "", owner_id)
        if existing:
            new_note = self._merge_note(existing.get("note"), data.get("note"))
            patch: dict[str, Any] = {"checked": False}
            if new_note:
                patch["note"] = new_note

            old_amt = existing.get("amount")
            new_amt = data.get("amount")
            old_unit = existing.get("unit")
            new_unit = data.get("unit")

            # Суммируем, если единицы совпадают или у старого нет единицы
            if old_amt and new_amt and (old_unit == new_unit or not old_unit):
                try:
                    num_old = float(str(old_amt).replace(",", "."))
                    num_new = float(str(new_amt).replace(",", "."))
                    total = num_old + num_new
                    patch["amount"] = int(total) if total.is_integer() else round(total, 2)
                    if not old_unit and new_unit:
                        patch["unit"] = new_unit
                except (ValueError, TypeError):
                    # Если не числа (например, "по вкусу"), пишем в заметку
                    note_add = f"добавлено: {new_amt} {new_unit or ''}".strip()
                    patch["note"] = self._merge_note(
                        patch.get("note", existing.get("note")), note_add
                    )
            elif not old_amt and new_amt:
                patch["amount"] = new_amt
                if new_unit:
                    patch["unit"] = new_unit

            updated = await self.update(existing["id"], owner_id, patch)
            return updated or existing, True
        item = await self.add(data, owner_id)
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

    async def update(self, item_id: str, owner_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "name", "amount", "unit", "brand", "barcode", "image_url",
            "category", "note", "checked", "recipe_id", "recipe_name", "source",
            "product_id",
        }
        clean = {k: v for k, v in patch.items() if k in allowed}

        async with SessionLocal() as session:
            row = await session.get(ShoppingItem, item_id)
            if not row or row.owner_id != owner_id:
                return None
            for key, value in clean.items():
                setattr(row, key, value)
            await session.commit()
            item = self._to_dict(row)
        self._cache_update(item)
        return item

    async def toggle(self, item_id: str, owner_id: str) -> dict[str, Any] | None:
        item = self.get(item_id)
        if not item or item.get("owner_id") != owner_id:
            return None
        return await self.update(
            item_id, owner_id, {"checked": not item.get("checked", False)}
        )

    async def delete(self, item_id: str, owner_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(ShoppingItem).where(
                    ShoppingItem.id == item_id,
                    ShoppingItem.owner_id == owner_id,
                )
            )
            await session.commit()
            deleted = bool(result.rowcount)
        if deleted:
            self._cache_remove(item_id)
        return deleted

    async def clear_checked(self, owner_id: str) -> int:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(ShoppingItem).where(
                    ShoppingItem.owner_id == owner_id,
                    ShoppingItem.checked.is_(True),
                )
            )
            await session.commit()
            removed = int(result.rowcount or 0)
        if removed:
            self.items = [
                i for i in self.items
                if not (i.get("owner_id") == owner_id and i.get("checked"))
            ]
        return removed

    async def clear_all(self, owner_id: str) -> int:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(ShoppingItem).where(ShoppingItem.owner_id == owner_id)
            )
            await session.commit()
            removed = int(result.rowcount or 0)
        if removed:
            self.items = [
                i for i in self.items if i.get("owner_id") != owner_id
            ]
        return removed


shopping_store = ShoppingStore()
