"""Единый шлюз для фоновых AI-задач.

Нормализатор, active_time и semantic enricher не должны работать
одновременно: на бесплатных ключах это создаёт лишнюю нагрузку и
мешает пользовательским запросам.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

_lock = asyncio.Lock()
_current: str | None = None


@asynccontextmanager
async def background_task(name: str) -> AsyncIterator[None]:
    global _current
    async with _lock:
        _current = name
        try:
            yield
        finally:
            _current = None


def busy() -> bool:
    return _lock.locked()


def current() -> str | None:
    return _current
