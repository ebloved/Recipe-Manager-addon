"""Аутентификация тонких клиентов по Bearer device-token."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select

from db import SessionLocal
from stores.db_models import DeviceToken

DEVICE_TOKEN_DAYS = 90


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def authenticate_device(request: Request) -> dict | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None

    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(DeviceToken).where(
                    DeviceToken.token_hash == hash_device_token(token)
                )
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            return None

        # Sliding expiry: обновляем не чаще раза в час.
        last_used = row.last_used_at
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=timezone.utc)
        if now - last_used > timedelta(hours=1):
            row.last_used_at = now
            row.expires_at = now + timedelta(days=DEVICE_TOKEN_DAYS)
            await session.commit()

        owner_id = row.owner_id

    from services.auth import users_store

    user = users_store.users.get(owner_id)
    if user:
        return user
    return {"id": owner_id, "role": "user", "name": "Device"}


async def require_device_user(request: Request) -> dict:
    user = getattr(request.state, "device_user", None)
    if not user:
        user = await authenticate_device(request)
    if not user:
        raise HTTPException(401, "Invalid or expired device token")
    return user
