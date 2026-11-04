"""Активный профиль генерации: персонально для каждого пользователя."""
from __future__ import annotations

from sqlalchemy import select

from db import SessionLocal
from stores.db_models import UserActiveProfile


class UserActiveProfilesRepository:
    async def get(self, owner_id: str) -> str | None:
        async with SessionLocal() as session:
            row = await session.get(UserActiveProfile, owner_id)
            return row.profile_id if row else None

    async def get_with_presence(self, owner_id: str) -> tuple[bool, str | None]:
        """(есть ли запись, profile_id). NULL — осознанный выбор «без профиля»."""
        async with SessionLocal() as session:
            row = await session.get(UserActiveProfile, owner_id)
            if row is None:
                return False, None
            return True, row.profile_id

    async def set(self, owner_id: str, profile_id: str | None) -> None:
        async with SessionLocal() as session:
            row = await session.get(UserActiveProfile, owner_id)
            if row is None:
                row = UserActiveProfile(owner_id=owner_id, profile_id=profile_id)
                session.add(row)
            else:
                row.profile_id = profile_id
            await session.commit()

    async def delete(self, owner_id: str) -> bool:
        async with SessionLocal() as session:
            row = await session.get(UserActiveProfile, owner_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


user_active_profiles = UserActiveProfilesRepository()
