"""HTTP-клиент публичного API Ашана.

Сайт закрыт QRATOR, но поисковый REST-эндпоинт `/v1/search` доступен
без авторизации и без браузера. Корзина через публичный API не найдена,
поэтому модуль используется только для поиска и ссылок.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from config import AUCHAN_API_BASE, AUCHAN_API_TIMEOUT, AUCHAN_USER_AGENT
from integrations.stores.auchan.models import AuchanProduct


class AuchanAPIError(Exception):
    pass


class AuchanClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        concurrency: int = 4,
        rate_limit_per_minute: int = 60,
    ) -> None:
        self._base_url = (base_url or AUCHAN_API_BASE).rstrip("/")
        self._timeout = timeout or AUCHAN_API_TIMEOUT
        self._semaphore = asyncio.Semaphore(concurrency)
        self._interval = 60.0 / rate_limit_per_minute if rate_limit_per_minute > 0 else 0.0
        self._last = 0.0
        self._limiter_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "User-Agent": AUCHAN_USER_AGENT,
                },
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _wait_rate(self) -> None:
        if self._interval <= 0:
            return
        async with self._limiter_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self._last + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            self._last = now

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._ensure_client()
        await self._wait_rate()
        async with self._semaphore:
            try:
                resp = await client.post(path, json=payload)
            except httpx.HTTPError as exc:
                raise AuchanAPIError(
                    f"Сеть недоступна: {type(exc).__name__}"
                ) from exc
        if resp.status_code != 200:
            raise AuchanAPIError(
                f"Ашан API HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise AuchanAPIError("Ашан API вернул не JSON") from exc
        if not isinstance(data, dict):
            raise AuchanAPIError("Ашан API вернул неожиданный ответ")
        return data

    @staticmethod
    def _flatten(data: dict[str, Any]) -> list[AuchanProduct]:
        out: list[AuchanProduct] = []
        for group in data.get("items") or []:
            for raw in group.get("products") or []:
                try:
                    out.append(AuchanProduct.model_validate(raw))
                except Exception:  # noqa: BLE001
                    continue
        return out

    async def search(
        self,
        query: str,
        merchant_id: int,
        *,
        page: int = 1,
    ) -> tuple[list[AuchanProduct], int | None]:
        data = await self._post(
            "/v1/search",
            {
                "query": query,
                "merchantId": int(merchant_id),
                "page": max(1, int(page)),
            },
        )
        counter = data.get("products_counter")
        try:
            total = int(counter) if counter is not None else None
        except (TypeError, ValueError):
            total = None
        return self._flatten(data), total

    async def merchant_has_products(self, merchant_id: int) -> bool:
        """Проверяет, что merchantId принимается и отдаёт непустой каталог."""
        products, total = await self.search("молоко", merchant_id)
        return bool(products) or bool(total)


auchan_client = AuchanClient()
