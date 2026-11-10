"""Device flow: подключение HA-аддона к серверу."""
from __future__ import annotations

import html
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from config import SERVER_PUBLIC_URL, SYNC_CONTRACT_VERSION
from db import SessionLocal
from services.auth import get_current_user
from services.device_auth import DEVICE_TOKEN_DAYS, hash_device_token
from services.secret_store import decrypt, encrypt
from stores.db_models import DeviceCode, DeviceToken

router = APIRouter(tags=["device"])

_CODE_TTL = 300
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


async def _log_device_failure(
    request: Request,
    user: dict | None,
    *,
    error: str,
    code: str,
    http_status: int,
) -> None:
    from services import audit

    actor = audit.resolve_actor((user or {}).get("id")) if user else {
        "kind": "anonymous", "id": None, "name": None, "email": None, "role": None,
    }
    try:
        await audit.log_event(
            action="auth.device",
            label="Неудачное подключение устройства",
            actor_kind=actor["kind"],
            actor_id=actor["id"],
            actor_name=actor["name"],
            actor_email=actor["email"],
            actor_role=actor["role"],
            status="denied",
            error=error,
            error_code=code,
            method=request.method,
            path=request.url.path,
            http_status=http_status,
            details={"stage": "device_auth"},
            ip=audit.client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[device-audit] failed: {type(exc).__name__}: {exc}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _user_code() -> str:
    left = "".join(secrets.choice(_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(_ALPHABET) for _ in range(4))
    return f"{left}-{right}"


def _base_url(request: Request) -> str:
    return (SERVER_PUBLIC_URL or str(request.base_url)).rstrip("/")


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#faf9f7;color:#1f1c19;display:flex;justify-content:center;padding:40px 16px}}
.card{{background:#fff;border:1px solid #e7e1da;border-radius:16px;padding:24px;max-width:460px;width:100%}}
h1{{font-size:22px;margin:0 0 12px}}p{{color:#6b6560}}
input{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #e7e1da;border-radius:10px;font-size:18px;letter-spacing:2px;text-transform:uppercase}}
button{{margin-top:14px;width:100%;padding:12px;border:0;border-radius:10px;background:#b45309;color:#fff;font-size:16px;font-weight:600;cursor:pointer}}
code{{background:#f4efe9;padding:2px 6px;border-radius:6px}}
a{{color:#b45309}} .msg{{padding:10px 12px;border-radius:10px;background:#ecfdf5;color:#065f46;margin-bottom:12px}}
.err{{background:#fef2f2;color:#991b1b}}
</style></head><body><div class="card">{body}</div></body></html>"""


@router.post("/api/v1/auth/device/init")
async def device_init(request: Request, payload: dict = Body(default={})):
    device_id = str(payload.get("device_id") or uuid.uuid4().hex)
    device_code = secrets.token_urlsafe(32)
    user_code = _user_code()
    expires = _now() + timedelta(seconds=_CODE_TTL)

    async with SessionLocal() as session:
        for _ in range(5):
            exists = (
                await session.execute(
                    select(DeviceCode).where(DeviceCode.user_code == user_code)
                )
            ).scalar_one_or_none()
            if exists is None:
                break
            user_code = _user_code()
        session.add(
            DeviceCode(
                device_code=device_code,
                user_code=user_code,
                device_id=device_id,
                status="pending",
                created_at=_now(),
                expires_at=expires,
            )
        )
        await session.commit()

    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": f"{_base_url(request)}/device",
        "expires_in": _CODE_TTL,
        "contract_version": SYNC_CONTRACT_VERSION,
    }


@router.post("/api/v1/auth/device/poll")
async def device_poll(request: Request, payload: dict = Body(...)):
    device_code = str(payload.get("device_code") or "").strip()
    if not device_code:
        raise HTTPException(400, "device_code is required")

    async with SessionLocal() as session:
        code = await session.get(DeviceCode, device_code)
        if code is None:
            await _log_device_failure(
                request,
                None,
                error="Код устройства не найден.",
                code="device_code_invalid",
                http_status=404,
            )
            raise HTTPException(404, "device_code not found")
        if _as_utc(code.expires_at) <= _now() and code.status == "pending":
            code.status = "expired"
            await session.commit()
            return {"status": "expired"}

        if code.status == "pending":
            return {"status": "pending"}
        if code.status in ("denied", "expired"):
            return {"status": code.status}
        if code.status != "approved" or not code.token_enc:
            return {"status": "pending"}

        token = decrypt(code.token_enc, context="device-tokens")
        owner_id = code.owner_id
        device_id = code.device_id
        await session.delete(code)
        await session.commit()

    if not token:
        raise HTTPException(500, "cannot decrypt device token")
    return {
        "status": "approved",
        "token": token,
        "owner_id": owner_id,
        "device_id": device_id,
    }


@router.post("/api/v1/auth/device/approve")
async def device_approve(request: Request, user_code: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(
            url="/api/auth/login?next=" + quote("/device"), status_code=302
        )

    code_value = user_code.strip().upper()
    async with SessionLocal() as session:
        code = (
            await session.execute(
                select(DeviceCode).where(DeviceCode.user_code == code_value)
            )
        ).scalar_one_or_none()
        if code is None:
            await _log_device_failure(
                request,
                user,
                error="Код устройства не найден.",
                code="device_code_invalid",
                http_status=400,
            )
            return _page(
                "Код не найден",
                "<h1>Код не найден</h1><p>Проверьте код и попробуйте снова.</p>"
                '<p><a href="/device">Назад</a></p>',
            )
        if _as_utc(code.expires_at) <= _now():
            code.status = "expired"
            await session.commit()
            await _log_device_failure(
                request,
                user,
                error="Код устройства истёк.",
                code="device_code_expired",
                http_status=410,
            )
            return _page(
                "Код истёк",
                "<h1>Код истёк</h1><p>Начните подключение заново в аддоне.</p>",
            )
        if code.status != "pending":
            await _log_device_failure(
                request,
                user,
                error="Код устройства уже использован.",
                code="device_code_used",
                http_status=409,
            )
            return _page(
                "Код уже использован",
                "<h1>Код уже использован</h1><p>Начните подключение заново.</p>",
            )

        raw_token = secrets.token_urlsafe(32)
        token = DeviceToken(
            id=uuid.uuid4().hex,
            token_hash=hash_device_token(raw_token),
            device_id=code.device_id,
            owner_id=user["id"],
            created_at=_now(),
            last_used_at=_now(),
            expires_at=_now() + timedelta(days=DEVICE_TOKEN_DAYS),
        )
        session.add(token)
        code.owner_id = user["id"]
        code.status = "approved"
        code.token_enc = encrypt(raw_token, context="device-tokens")
        await session.commit()

    return RedirectResponse(url="/device?ok=1", status_code=302)


@router.get("/device", response_class=HTMLResponse, include_in_schema=False)
async def device_page(request: Request, code: str = "", ok: int = 0):
    user = get_current_user(request)
    if not user:
        return HTMLResponse(
            _page(
                "Подключение устройства",
                "<h1>Подключение устройства</h1>"
                "<p>Сначала войдите в Recipe Manager.</p>"
                '<p><a href="/api/auth/login?next=%2Fdevice">Войти</a></p>',
            )
        )

    message = (
        '<div class="msg">Устройство подключено. Вернитесь в аддон.</div>'
        if ok else ""
    )
    return HTMLResponse(
        _page(
            "Подключение устройства",
            f"{message}<h1>Подключение устройства</h1>"
            "<p>Введите код, который показывает HA-аддон.</p>"
            '<form method="post" action="/api/v1/auth/device/approve">'
            f'<input name="user_code" value="{html.escape(code)}" '
            'placeholder="ABCD-EFGH" autocomplete="off" required>'
            '<button type="submit">Подключить</button></form>'
            f"<p>Вы вошли как <b>{html.escape(user.get('name') or '')}</b>.</p>",
        )
    )
