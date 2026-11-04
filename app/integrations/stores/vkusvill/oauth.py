"""ВкусВилл OAuth 2.0 + PKCE (per-user, stateless service + SQLite tokens)."""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, select

from config import (
    VKUSVILL_AUTH_URL,
    VKUSVILL_CLIENT_ID,
    VKUSVILL_CLIENT_SECRET,
    VKUSVILL_PROXY,
    VKUSVILL_REDIRECT_URI,
    VKUSVILL_REVOKE_URL,
    VKUSVILL_SCOPES,
    VKUSVILL_TOKEN_URL,
)
from db import SessionLocal
from stores.db_models import OAuthState
from stores.store_credentials import store_credentials

STORE_ID = "vkusvill"
STATE_TTL_SECONDS = 600


class StoreNotConnected(Exception):
    pass


class StoreOAuthError(Exception):
    pass


def is_configured() -> bool:
    return bool(
        VKUSVILL_CLIENT_ID
        and VKUSVILL_CLIENT_SECRET
        and VKUSVILL_REDIRECT_URI
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def _cleanup_states() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STATE_TTL_SECONDS)
    async with SessionLocal() as session:
        await session.execute(
            delete(OAuthState).where(OAuthState.created_at < cutoff)
        )
        await session.commit()


async def create_authorization_url(owner_id: str, store_id: str = STORE_ID) -> str:
    if not is_configured():
        raise StoreOAuthError("VkusVill OAuth is not configured")

    await _cleanup_states()
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    redirect_uri = VKUSVILL_REDIRECT_URI

    async with SessionLocal() as session:
        session.add(
            OAuthState(
                state=state,
                owner_id=owner_id,
                store_id=store_id,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    params = {
        "response_type": "code",
        "client_id": VKUSVILL_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": VKUSVILL_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{VKUSVILL_AUTH_URL}?{urlencode(params)}"


async def _token_request(
    data: dict[str, str],
    *,
    use_basic_auth: bool = False,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    auth = None
    if use_basic_auth:
        auth = (VKUSVILL_CLIENT_ID, VKUSVILL_CLIENT_SECRET)
        data = {k: v for k, v in data.items() if k not in ("client_id", "client_secret")}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        proxy=VKUSVILL_PROXY,
    ) as client:
        resp = await client.post(
            VKUSVILL_TOKEN_URL,
            data=data,
            headers=headers,
            auth=auth,
        )

    if resp.status_code != 200:
        try:
            body = resp.json()
            detail = body.get("error_description") or body.get("error") or ""
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        raise StoreOAuthError(
            f"VkusVill token request failed: HTTP {resp.status_code} {detail}".strip()
        )

    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise StoreOAuthError("VkusVill token response is not JSON") from exc


async def exchange_code(state: str, code: str, owner_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(OAuthState).where(OAuthState.state == state)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise StoreOAuthError("OAuth state not found or already used")
        created = _as_utc(row.created_at)
        if created and datetime.now(timezone.utc) - created > timedelta(seconds=STATE_TTL_SECONDS):
            await session.delete(row)
            await session.commit()
            raise StoreOAuthError("OAuth state expired")
        if row.owner_id != owner_id:
            raise StoreOAuthError("OAuth state owner mismatch")
        store_id = row.store_id
        verifier = row.code_verifier
        redirect_uri = row.redirect_uri
        await session.delete(row)
        await session.commit()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": VKUSVILL_CLIENT_ID,
        "client_secret": VKUSVILL_CLIENT_SECRET,
        "code_verifier": verifier,
    }
    try:
        body = await _token_request(data)
    except StoreOAuthError:
        # Некоторые OAuth-серверы требуют client_secret_basic.
        body = await _token_request(data, use_basic_auth=True)

    access_token = body.get("access_token")
    if not access_token:
        raise StoreOAuthError("VkusVill response has no access_token")

    expires_in = body.get("expires_in")
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    await store_credentials.upsert_tokens(
        owner_id,
        store_id,
        access_token=access_token,
        refresh_token=body.get("refresh_token"),
        token_type=body.get("token_type") or "Bearer",
        expires_at=expires_at,
        scopes=body.get("scope") or VKUSVILL_SCOPES,
    )
    print(f"[vkusvill] OAuth connected for owner={owner_id}")
    return {
        "store_id": store_id,
        "expires_at": expires_at,
        "scopes": body.get("scope") or VKUSVILL_SCOPES,
    }


async def refresh_access_token(owner_id: str, store_id: str = STORE_ID) -> str | None:
    creds = await store_credentials.get(owner_id, store_id)
    if not creds or not creds.get("refresh_token"):
        return None

    data = {
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
        "client_id": VKUSVILL_CLIENT_ID,
        "client_secret": VKUSVILL_CLIENT_SECRET,
    }
    try:
        body = await _token_request(data)
    except StoreOAuthError:
        body = await _token_request(data, use_basic_auth=True)

    access_token = body.get("access_token")
    if not access_token:
        return None
    expires_in = body.get("expires_in")
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    await store_credentials.upsert_tokens(
        owner_id,
        store_id,
        access_token=access_token,
        refresh_token=body.get("refresh_token"),
        token_type=body.get("token_type") or creds.get("token_type") or "Bearer",
        expires_at=expires_at,
        scopes=body.get("scope") or creds.get("scopes"),
    )
    print(f"[vkusvill] OAuth token refreshed for owner={owner_id}")
    return access_token


async def get_valid_access_token(owner_id: str, store_id: str = STORE_ID) -> str:
    creds = await store_credentials.get(owner_id, store_id)
    if not creds or not creds.get("access_token"):
        raise StoreNotConnected("VkusVill is not connected for this user")

    expires_at = _as_utc(creds.get("expires_at"))
    if expires_at and expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
        refreshed = await refresh_access_token(owner_id, store_id)
        if refreshed:
            return refreshed
        raise StoreNotConnected("VkusVill token expired and refresh failed")

    return creds["access_token"]


async def revoke(owner_id: str, store_id: str = STORE_ID) -> None:
    creds = await store_credentials.get(owner_id, store_id)
    if creds and creds.get("access_token"):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                proxy=VKUSVILL_PROXY,
            ) as client:
                await client.post(
                    VKUSVILL_REVOKE_URL,
                    data={
                        "token": creds["access_token"],
                        "client_id": VKUSVILL_CLIENT_ID,
                        "client_secret": VKUSVILL_CLIENT_SECRET,
                    },
                    headers={"Accept": "application/json"},
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[vkusvill] revoke failed (ignored): {type(exc).__name__}")
    await store_credentials.delete(owner_id, store_id)
    print(f"[vkusvill] OAuth disconnected for owner={owner_id}")
