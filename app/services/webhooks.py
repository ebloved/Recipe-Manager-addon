"""Webhook-уведомления внешним коннекторам при изменении данных.

Отправляется PUT с тем же JSON, что отдаёт `/api/v1/export/shopping`.
Подпись: HMAC-SHA256 от тела, ключ — SHA-256 от API-токена.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx

from stores.api_tokens import api_tokens

_RETRY_DELAYS = (0, 1, 5)


class WebhookManager:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Task] = {}
        self._pending_events: dict[str, set[str]] = {}

    def schedule(
        self,
        owner_id: str | None,
        *,
        event: str = "shopping",
        delay: float = 2.0,
    ) -> None:
        if not owner_id:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._pending_events.setdefault(owner_id, set()).add(event)
        old = self._pending.pop(owner_id, None)
        if old is not None:
            old.cancel()
        self._pending[owner_id] = asyncio.create_task(
            self._debounced(owner_id, delay)
        )

    async def _debounced(self, owner_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        events = self._pending_events.pop(owner_id, {"shopping"})
        try:
            await self._deliver(owner_id, events)
        except Exception as exc:  # noqa: BLE001
            print(f"[webhook] delivery failed: {type(exc).__name__}: {exc}")
        finally:
            self._pending.pop(owner_id, None)

    async def _payload(self, owner_id: str, source: str) -> dict[str, Any]:
        from services.export_items import build_export
        from services.auth import users_store

        user = users_store.users.get(owner_id) or {"id": owner_id}
        return build_export(
            owner_id,
            source=source,
            include_checked=False,
            merge=True,
            include_recipes=True,
            user=user,
        )

    async def _deliver(self, owner_id: str, events: set[str]) -> None:
        tokens = await api_tokens.list_with_callbacks(owner_id)
        if not tokens:
            return
        for token in tokens:
            url = token.get("callback_url")
            if not url:
                continue
            source = token.get("callback_events") or "shopping"
            if source != "both" and source not in events:
                continue
            try:
                payload = await self._payload(owner_id, source)
            except Exception as exc:  # noqa: BLE001
                await api_tokens.record_delivery(
                    owner_id,
                    token["id"],
                    status="error",
                    error=f"{type(exc).__name__}: {exc}"[:500],
                )
                continue
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            signature = hmac.new(
                token["token_hash"].encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "RecipeManager-Webhook/1.0",
                "X-Recipe-Manager-Event": "cart.updated",
                "X-Recipe-Manager-Revision": payload["revision"],
                "X-Recipe-Manager-Token-Id": token["id"],
                "X-Recipe-Manager-Signature": f"sha256={signature}",
                "Idempotency-Key": payload["revision"],
            }
            status, error = await self._put(url, body, headers)
            await api_tokens.record_delivery(
                owner_id,
                token["id"],
                status=status,
                error=error,
            )

    async def _put(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[str, str | None]:
        last_error = None
        for index, delay in enumerate(_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0),
                    follow_redirects=True,
                ) as client:
                    resp = await client.put(url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    return f"ok:{resp.status_code}", None
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code == 429 or resp.status_code >= 500:
                    continue
                return f"http:{resp.status_code}", last_error
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if index < len(_RETRY_DELAYS) - 1:
                    continue
        return "error", last_error

    async def send_test(self, owner_id: str, token_id: str) -> dict[str, Any] | None:
        token = await api_tokens.get_with_hash(owner_id, token_id)
        if token is None or not token.get("callback_url"):
            return None
        source = token.get("callback_events") or "shopping"
        payload = await self._payload(owner_id, source)
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        signature = hmac.new(
            token["token_hash"].encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RecipeManager-Webhook/1.0",
            "X-Recipe-Manager-Event": "webhook.test",
            "X-Recipe-Manager-Revision": payload["revision"],
            "X-Recipe-Manager-Token-Id": token["id"],
            "X-Recipe-Manager-Test": "1",
            "X-Recipe-Manager-Signature": f"sha256={signature}",
            "Idempotency-Key": f"test-{payload['revision']}",
        }
        status, error = await self._put(token["callback_url"], body, headers)
        await api_tokens.record_delivery(
            owner_id, token_id, status=status, error=error
        )
        return {
            "ok": status.startswith("ok:"),
            "status": status,
            "error": error,
        }

    async def close(self) -> None:
        tasks = list(self._pending.values())
        self._pending.clear()
        self._pending_events.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


webhook_manager = WebhookManager()
