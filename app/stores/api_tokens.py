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
_ALLOWED_EVENTS = {"shopping", "meal_plan", "both"}


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


def normalize_events(value: Any) -> str:
    events = str(value or "shopping").strip().lower()
    return events if events in _ALLOWED_EVENTS else "shopping"


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

    async def verify(
        self,
        token: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any] | None:
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
            if ip:
                row.last_ip = ip[:64]
            if user_agent:
                row.last_user_agent = user_agent[:300]
            await session.commit()
            return self._to_dict(row)

    async def set_webhook(
        self,
        owner_id: str,
        token_id: str,
        *,
        callback_url: str | None,
        callback_events: str | None,
    ) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserApiToken).where(
                    UserApiToken.id == token_id,
                    UserApiToken.owner_id == str(owner_id),
                    UserApiToken.revoked_at.is_(None),
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            row.callback_url = (callback_url or "").strip() or None
            row.callback_events = normalize_events(callback_events)
            await session.commit()
            return self._to_dict(row)

    async def record_delivery(
        self,
        owner_id: str,
        token_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            row = await session.get(UserApiToken, token_id)
            if row is None or row.owner_id != str(owner_id):
                return
            row.last_delivery_at = datetime.now(timezone.utc)
            row.last_delivery_status = status[:32]
            row.last_delivery_error = (error or "")[:1000] or None
            await session.commit()

    async def list_with_callbacks(self, owner_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserApiToken).where(
                    UserApiToken.owner_id == str(owner_id),
                    UserApiToken.revoked_at.is_(None),
                    UserApiToken.callback_url.is_not(None),
                )
            )
            rows = result.scalars().all()
        out = []
        for row in rows:
            item = self._to_dict(row)
            item["token_hash"] = row.token_hash
            out.append(item)
        return out

    async def get_with_hash(self, owner_id: str, token_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserApiToken).where(
                    UserApiToken.id == token_id,
                    UserApiToken.owner_id == str(owner_id),
                    UserApiToken.revoked_at.is_(None),
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            item = self._to_dict(row)
            item["token_hash"] = row.token_hash
            return item

    @staticmethod
    def _to_dict(row: UserApiToken) -> dict[str, Any]:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "prefix": row.token_prefix,
            "scopes": [s for s in (row.scopes or "").split(",") if s],
            "callback_url": row.callback_url,
            "callback_events": row.callback_events or "shopping",
            "last_ip": row.last_ip,
            "last_user_agent": row.last_user_agent,
            "last_delivery_at": _as_utc(row.last_delivery_at),
            "last_delivery_status": row.last_delivery_status,
            "last_delivery_error": row.last_delivery_error,
            "created_at": _as_utc(row.created_at),
            "last_used_at": _as_utc(row.last_used_at),
            "revoked_at": _as_utc(row.revoked_at),
        }


api_tokens = ApiTokenRepository()
