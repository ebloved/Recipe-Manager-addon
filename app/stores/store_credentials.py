"""Per-user OAuth-токены магазинов (SQLite, шифрование Fernet)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from db import SessionLocal
from services.secret_store import decrypt, encrypt
from stores.db_models import UserStoreCredential


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class StoreCredentialsRepository:
    async def get(self, owner_id: str, store_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserStoreCredential).where(
                    UserStoreCredential.owner_id == owner_id,
                    UserStoreCredential.store_id == store_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "owner_id": row.owner_id,
                "store_id": row.store_id,
                "client_id": decrypt(row.client_id_enc),
                "client_secret": decrypt(row.client_secret_enc),
                "access_token": decrypt(row.access_token_enc),
                "refresh_token": decrypt(row.refresh_token_enc),
                "token_type": row.token_type or "Bearer",
                "expires_at": _as_utc(row.expires_at),
                "scopes": row.scopes,
                "created_at": _as_utc(row.created_at),
                "updated_at": _as_utc(row.updated_at),
            }

    async def is_connected(self, owner_id: str, store_id: str) -> bool:
        creds = await self.get(owner_id, store_id)
        return bool(creds and creds.get("access_token"))

    async def upsert_tokens(
        self,
        owner_id: str,
        store_id: str,
        *,
        access_token: str,
        refresh_token: str | None,
        token_type: str = "Bearer",
        expires_at: datetime | None = None,
        scopes: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserStoreCredential).where(
                    UserStoreCredential.owner_id == owner_id,
                    UserStoreCredential.store_id == store_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UserStoreCredential(owner_id=owner_id, store_id=store_id)
                session.add(row)
            row.access_token_enc = encrypt(access_token)
            row.refresh_token_enc = encrypt(refresh_token) if refresh_token else row.refresh_token_enc
            row.token_type = token_type or "Bearer"
            row.expires_at = expires_at
            if scopes is not None:
                row.scopes = scopes
            await session.commit()

    async def upsert_client(
        self,
        owner_id: str,
        store_id: str,
        *,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserStoreCredential).where(
                    UserStoreCredential.owner_id == owner_id,
                    UserStoreCredential.store_id == store_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UserStoreCredential(owner_id=owner_id, store_id=store_id)
                session.add(row)
            row.client_id_enc = encrypt(client_id)
            row.client_secret_enc = encrypt(client_secret)
            await session.commit()

    async def delete(self, owner_id: str, store_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(UserStoreCredential).where(
                    UserStoreCredential.owner_id == owner_id,
                    UserStoreCredential.store_id == store_id,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def list_for_owner(self, owner_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserStoreCredential).where(
                    UserStoreCredential.owner_id == owner_id
                )
            )
            rows = result.scalars().all()
        out = []
        for row in rows:
            out.append({
                "store_id": row.store_id,
                "token_type": row.token_type,
                "expires_at": _as_utc(row.expires_at),
                "scopes": row.scopes,
                "updated_at": _as_utc(row.updated_at),
            })
        return out


store_credentials = StoreCredentialsRepository()
