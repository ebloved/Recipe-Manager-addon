"""Stateless JSON-RPC клиент MCP ВкусВилла (Bearer token per call)."""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

import httpx

from config import (
    VKUSVILL_MCP_TIMEOUT,
    VKUSVILL_MCP_URL,
    VKUSVILL_PROXY,
)


class MCPError(Exception):
    pass


class MCPUnauthorized(MCPError):
    pass


class MCPToolError(MCPError):
    pass


class RateLimiter:
    def __init__(self, max_per_minute: int = 50) -> None:
        self._interval = 60.0 / max_per_minute if max_per_minute > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self._last + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            self._last = now


class VkusVillMCPClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        timeout: float | None = None,
        concurrency: int = 5,
        rate_limit_per_minute: int = 50,
    ) -> None:
        self._url = url or VKUSVILL_MCP_URL
        self._timeout = timeout or VKUSVILL_MCP_TIMEOUT
        self._semaphore = asyncio.Semaphore(concurrency)
        self._limiter = RateLimiter(rate_limit_per_minute)
        self._ids = itertools.count(1)
        self._client: httpx.AsyncClient | None = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=httpx.Timeout(self._timeout),
                proxy=VKUSVILL_PROXY,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure_client()
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params or {},
        }
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        await self._limiter.acquire()
        async with self._semaphore:
            try:
                resp = await client.post(self._url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise MCPError(f"MCP network error: {type(exc).__name__}") from exc

        if resp.status_code == 401:
            raise MCPUnauthorized("MCP returned 401 — invalid Bearer token")
        if resp.status_code != 200:
            raise MCPError(f"MCP HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP non-JSON response: {resp.text[:300]}") from exc

        if "error" in data:
            error = data["error"]
            raise MCPError(
                f"MCP JSON-RPC error {error.get('code')}: {error.get('message')}"
            )
        return data.get("result", {})

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self._rpc(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "recipe-manager",
                        "version": "3.7.0",
                    },
                },
            )
            self._initialized = True

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        token: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_initialized()
        result = await self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            token=token,
        )
        if result.get("isError"):
            raise MCPToolError(f"Tool {name} returned isError=true")
        content = result.get("content") or []
        if not content:
            raise MCPToolError(f"Tool {name} returned empty content")
        text = content[0].get("text", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MCPToolError(
                f"Tool {name} returned non-JSON text: {text[:200]}"
            ) from exc
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            raise MCPToolError(f"Tool {name} returned ok=false: {parsed}")
        if isinstance(parsed, dict) and "data" in parsed:
            return parsed["data"]
        return parsed if isinstance(parsed, dict) else {"value": parsed}


vkusvill_mcp = VkusVillMCPClient()
