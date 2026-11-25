"""Персональные API-токены для внешних коннекторов."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from db import SessionLocal
from stores.db_models import UserApiToken

_TOKEN_PREFIX = "rm_"
_ALLOWED_SCOPES = {"export", "products:write"}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_scopes(scopes: Any) -> list[str]:
    if scopes is None:
        return ["export"]
    if isinstance(scopes, str):
        values = scopes.split(",")
    elif isinstance(scopes, list):
        values = scopes
    else:
        values = []
    out = []
    for value in values:
        scope = str(value).strip()
        if scope in _ALLOWED_SCOPES and scope not in out:
            out.append(scope)
    return out or ["export"]


class ApiTokenRepository:
    async def create(
        self,
        owner_id: str,
        *,
        name: str = "API token",
        scopes: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
        token_id = uuid.uuid4().hex
        scope_list = normalize_scopes(scopes)
        row = UserApiToken(
            id=token_id,
            owner_id=str(owner_id),
            name=(name or "API token").strip()[:200] or "API token",
            token_hash=_hash_token(token),
            token_prefix=token[:14] + "…",
            scopes=",".join(scope_list),
        )
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
        return token, self._to_dict(row)

    async def list(self, owner_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserApiToken)
                .where(UserApiToken.owner_id == str(owner_id))
                .order_by(UserApiToken.created_at.desc())
            )
            rows = result.scalars().all()
        return [self._to_dict(row) for row in rows]

    async def revoke(self, owner_id: str, token_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserApiToken).where(
                    UserApiToken.id == token_id,
                    UserApiToken.owner_id == str(owner_id),
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return False
            if row.revoked_at is None:
                row.revoked_at = datetime.now(timezone.utc)
                await session.commit()
            return True

    async def verify(self, token: str) -> dict[str, Any] | None:
        if not token or not token.startswith(_TOKEN_PREFIX):
            return None
        token_hash = _hash_token(token)
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserApiToken).where(
                    UserApiToken.token_hash == token_hash,
                    UserApiToken.revoked_at.is_(None),
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            row.last_used_at = datetime.now(timezone.utc)
            await session.commit()
            return self._to_dict(row)

    @staticmethod
    def _to_dict(row: UserApiToken) -> dict[str, Any]:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "prefix": row.token_prefix,
            "scopes": [s for s in (row.scopes or "").split(",") if s],
            "created_at": _as_utc(row.created_at),
            "last_used_at": _as_utc(row.last_used_at),
            "revoked_at": _as_utc(row.revoked_at),
        }


api_tokens = ApiTokenRepository()
