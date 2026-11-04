"""Текущая сессия «Готовлю сейчас» (SQLite)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from db import SessionLocal
from stores.db_models import CurrentCookingSession


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class CookingSessionRepository:
    async def get(self, user_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(CurrentCookingSession).where(
                    CurrentCookingSession.user_id == user_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "user_id": row.user_id,
                "main_recipe_id": row.main_recipe_id,
                "side_recipe_id": row.side_recipe_id,
                "checked_ingredients": list(row.checked_ingredients or []),
                "created_at": _as_utc(row.created_at),
                "updated_at": _as_utc(row.updated_at),
            }

    async def upsert(
        self,
        user_id: str,
        *,
        main_recipe_id: str | None,
        side_recipe_id: str | None,
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(CurrentCookingSession).where(
                    CurrentCookingSession.user_id == user_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = CurrentCookingSession(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    main_recipe_id=main_recipe_id,
                    side_recipe_id=side_recipe_id,
                    checked_ingredients=[],
                )
                session.add(row)
            else:
                same = (
                    row.main_recipe_id == main_recipe_id
                    and row.side_recipe_id == side_recipe_id
                )
                row.main_recipe_id = main_recipe_id
                row.side_recipe_id = side_recipe_id
                if not same:
                    row.checked_ingredients = []
            await session.commit()
            return {
                "id": row.id,
                "user_id": row.user_id,
                "main_recipe_id": row.main_recipe_id,
                "side_recipe_id": row.side_recipe_id,
                "checked_ingredients": list(row.checked_ingredients or []),
                "created_at": _as_utc(row.created_at),
                "updated_at": _as_utc(row.updated_at),
            }

    async def update_checked(
        self, user_id: str, checked: list[str]
    ) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(CurrentCookingSession).where(
                    CurrentCookingSession.user_id == user_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            row.checked_ingredients = list(dict.fromkeys(checked))
            await session.commit()
            return {
                "id": row.id,
                "user_id": row.user_id,
                "main_recipe_id": row.main_recipe_id,
                "side_recipe_id": row.side_recipe_id,
                "checked_ingredients": list(row.checked_ingredients or []),
                "created_at": _as_utc(row.created_at),
                "updated_at": _as_utc(row.updated_at),
            }

    async def delete(self, user_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(CurrentCookingSession).where(
                    CurrentCookingSession.user_id == user_id
                )
            )
            await session.commit()
            return bool(result.rowcount)


cooking_sessions = CookingSessionRepository()
