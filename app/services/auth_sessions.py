"""Учёт OAuth-сессий: первичный вход и возврат после простоя."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete

from db import SessionLocal
from stores.db_models import AuthSession

SESSION_RESUME_IDLE_SECONDS = 30 * 60
SESSION_TOUCH_THROTTLE_SECONDS = 60
SESSION_RETENTION_DAYS = 30
_MAX_UA = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def session_key(payload: dict[str, Any] | None, token: str | None) -> str | None:
    """Ключ сессии: sid из cookie или hash старого токена без sid."""
    if payload and payload.get("sid"):
        return str(payload["sid"])
    if token:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:64]
    return None


def _client_ip(request) -> str | None:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for", ""
    )
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or None
    return request.client.host[:64] if request.client else None


def _user_agent(request) -> str | None:
    return (request.headers.get("user-agent") or "")[:_MAX_UA] or None


async def register_login(
    user_id: str,
    sid: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Создаёт/обновляет запись сессии при OAuth-входе."""
    if not sid:
        return
    now = _now()
    async with SessionLocal() as session:
        row = await session.get(AuthSession, sid)
        if row is None:
            row = AuthSession(
                sid=sid,
                user_id=user_id,
                source="oauth",
                created_at=now,
                last_seen_at=now,
                login_ip=ip,
                last_ip=ip,
                user_agent=user_agent,
            )
            session.add(row)
        else:
            row.user_id = user_id
            row.last_seen_at = now
            row.last_ip = ip
            row.user_agent = user_agent
            row.revoked_at = None
        await session.commit()


async def touch_session(
    key: str,
    user_id: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    source: str = "oauth",
) -> dict[str, Any]:
    """Обновляет last_seen и сообщает, создана ли сессия/был ли простой."""
    now = _now()
    async with SessionLocal() as session:
        row = await session.get(AuthSession, key)
        if row is None:
            row = AuthSession(
                sid=key,
                user_id=user_id,
                source=source,
                created_at=now,
                last_seen_at=now,
                login_ip=ip,
                last_ip=ip,
                user_agent=user_agent,
            )
            session.add(row)
            await session.commit()
            return {
                "created": True,
                "resumed": False,
                "idle_seconds": 0,
                "revoked": False,
            }

        last = _as_utc(row.last_seen_at)
        idle_seconds = max(0, int((now - last).total_seconds()))
        resumed = idle_seconds >= SESSION_RESUME_IDLE_SECONDS
        if idle_seconds >= SESSION_TOUCH_THROTTLE_SECONDS:
            row.last_seen_at = now
            row.last_ip = ip
            row.user_agent = user_agent
            row.user_id = user_id
            await session.commit()
        return {
            "created": False,
            "resumed": resumed,
            "idle_seconds": idle_seconds,
            "revoked": bool(row.revoked_at),
        }


async def revoke_session(key: str | None) -> None:
    if not key:
        return
    now = _now()
    async with SessionLocal() as session:
        row = await session.get(AuthSession, key)
        if row is not None:
            row.revoked_at = now
            row.last_seen_at = now
            await session.commit()


async def cleanup_old(days: int = SESSION_RETENTION_DAYS) -> int:
    cutoff = _now() - timedelta(days=max(1, int(days)))
    async with SessionLocal() as session:
        result = await session.execute(
            delete(AuthSession).where(AuthSession.last_seen_at < cutoff)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def audit_current_session(request) -> None:
    """Пишет auth.session при первом использовании cookie или после простоя."""
    try:
        from config import AUTH_MODE

        if AUTH_MODE != "oauth":
            return

        from services.auth import (
            SESSION_COOKIE,
            get_current_user,
            read_session_payload,
        )

        token = request.cookies.get(SESSION_COOKIE)
        payload = read_session_payload(token)
        if not payload:
            return
        user = get_current_user(request)
        if not user:
            return
        key = session_key(payload, token)
        if not key:
            return
        ip = _client_ip(request)
        ua = _user_agent(request)
        source = "oauth" if payload.get("sid") else "legacy"
        result = await touch_session(
            key,
            str(user.get("id")),
            ip=ip,
            user_agent=ua,
            source=source,
        )
        if not (result["created"] or result["resumed"]):
            return

        from services import audit

        actor = audit.resolve_actor(user.get("id"))
        reason = "first_seen" if result["created"] else "resumed_after_idle"
        await audit.log_event(
            action="auth.session",
            label="Сессия пользователя",
            actor_kind=actor["kind"],
            actor_id=actor["id"],
            actor_name=actor["name"],
            actor_email=actor["email"],
            actor_role=actor["role"],
            target_type="session",
            target_id=key,
            target_name=actor["name"],
            status="ok",
            details={
                "session_id": key,
                "reason": reason,
                "idle_minutes": round(result["idle_seconds"] / 60, 1),
                "legacy": payload.get("sid") is None,
                "source": source,
                "ip": ip,
                "user_agent": ua,
            },
            ip=ip,
            user_agent=ua,
            correlation_id=key,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[auth-session] audit failed: {type(exc).__name__}: {exc}")
