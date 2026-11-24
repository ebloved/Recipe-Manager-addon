"""Per-user настройки магазинов без OAuth (адрес доставки Ленты)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from db import SessionLocal
from stores.db_models import UserStoreSetting


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class StoreSettingsRepository:
    async def get(self, owner_id: str, store_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserStoreSetting).where(
                    UserStoreSetting.owner_id == owner_id,
                    UserStoreSetting.store_id == store_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "owner_id": row.owner_id,
                "store_id": row.store_id,
                "address": row.address,
                "store_alias_id": row.store_alias_id,
                "store_name": row.store_name,
                "created_at": _as_utc(row.created_at),
                "updated_at": _as_utc(row.updated_at),
            }

    async def upsert(
        self,
        owner_id: str,
        store_id: str,
        *,
        address: str | None = None,
        store_alias_id: int | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserStoreSetting).where(
                    UserStoreSetting.owner_id == owner_id,
                    UserStoreSetting.store_id == store_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UserStoreSetting(owner_id=owner_id, store_id=store_id)
                session.add(row)
            if address is not None:
                row.address = address
            row.store_alias_id = store_alias_id
            row.store_name = store_name
            await session.commit()
            return {
                "owner_id": row.owner_id,
                "store_id": row.store_id,
                "address": row.address,
                "store_alias_id": row.store_alias_id,
                "store_name": row.store_name,
            }

    async def delete(self, owner_id: str, store_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(UserStoreSetting).where(
                    UserStoreSetting.owner_id == owner_id,
                    UserStoreSetting.store_id == store_id,
                )
            )
            await session.commit()
            return bool(result.rowcount)


store_settings = StoreSettingsRepository()
