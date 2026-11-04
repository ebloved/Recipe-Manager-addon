"""Remote-клиент (BFF): подключение аддона к серверу по device flow."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException

from config import (
    DATA_DIR,
    REMOTE_ALLOW_PRIVATE_URLS,
    REMOTE_DEVICE_TOKEN,
    REMOTE_MODE,
    REMOTE_SERVER_URL,
)
from services.secret_store import decrypt, encrypt
from services.url_guard import UnsafeURLError, validate_public_url

TOKEN_FILE = DATA_DIR / "remote_device_token.enc"
SERVER_FILE = DATA_DIR / "remote_server.json"
_PAIR_TIMEOUT = 30.0


def get_server_url() -> str:
    if REMOTE_SERVER_URL:
        return REMOTE_SERVER_URL.rstrip("/")
    try:
        data = json.loads(SERVER_FILE.read_text(encoding="utf-8"))
        return str(data.get("server_url") or "").rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


def set_server_url(url: str) -> str:
    clean = (url or "").strip().rstrip("/")
    if clean:
        try:
            validate_public_url(clean, allow_private=REMOTE_ALLOW_PRIVATE_URLS)
        except UnsafeURLError as exc:
            hint = ""
            if not REMOTE_ALLOW_PRIVATE_URLS and "private/reserved" in str(exc):
                hint = (
                    " — для локального сервера включите "
                    "remote_allow_private_urls в Configuration аддона"
                )
            raise HTTPException(400, f"unsafe server URL: {exc}{hint}") from exc
        SERVER_FILE.write_text(
            json.dumps({"server_url": clean}, ensure_ascii=False), encoding="utf-8"
        )
        try:
            os.chmod(SERVER_FILE, 0o600)
        except OSError:
            pass
    return clean


def get_token() -> str:
    if REMOTE_DEVICE_TOKEN:
        return REMOTE_DEVICE_TOKEN
    if not TOKEN_FILE.exists():
        return ""
    try:
        raw = TOKEN_FILE.read_text(encoding="utf-8")
        return decrypt(raw, context="remote-device") or ""
    except Exception:  # noqa: BLE001
        return ""


def save_token(token: str) -> None:
    enc = encrypt(token, context="remote-device")
    if not enc:
        raise HTTPException(500, "cannot encrypt remote token")
    TOKEN_FILE.write_text(enc, encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def clear_token() -> None:
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass


def is_paired() -> bool:
    return bool(get_token() and get_server_url())


def status() -> dict[str, Any]:
    return {
        "remote_mode": REMOTE_MODE,
        "server_url": get_server_url(),
        "paired": is_paired(),
    }


async def pair_init(server_url: str, device_id: str | None = None) -> dict[str, Any]:
    base = set_server_url(server_url)
    if not base:
        raise HTTPException(400, "server_url is required")
    payload = {"device_id": device_id or uuid.uuid4().hex}
    try:
        async with httpx.AsyncClient(timeout=_PAIR_TIMEOUT) as client:
            resp = await client.post(
                urljoin(base + "/", "api/v1/auth/device/init"), json=payload
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"server unavailable: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(502, f"server error HTTP {resp.status_code}: {resp.text[:200]}")
    return {"server_url": base, **resp.json()}


async def pair_poll(server_url: str, device_code: str) -> dict[str, Any]:
    base = set_server_url(server_url)
    if not base:
        raise HTTPException(400, "server_url is required")
    try:
        async with httpx.AsyncClient(timeout=_PAIR_TIMEOUT) as client:
            resp = await client.post(
                urljoin(base + "/", "api/v1/auth/device/poll"),
                json={"device_code": device_code},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"server unavailable: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(502, f"server error HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("status") == "approved" and data.get("token"):
        save_token(str(data["token"]))
        data["paired"] = True
        data.pop("token", None)
    return data


async def ping() -> bool:
    server = get_server_url()
    if not server:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(urljoin(server + "/", "api/v1/health"))
        return resp.status_code == 200
    except httpx.HTTPError:
        return False
