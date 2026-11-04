"""Фоновый semantic enricher: один рецепт, только в простое."""
from __future__ import annotations

import asyncio

from config import (
    SEMANTIC_ENRICHER_ENABLED,
    SEMANTIC_ENRICHER_IDLE_SECONDS,
    SEMANTIC_ENRICHER_INTERVAL_SECONDS,
)
from services import semantic_enricher
from services.activity import is_active
from services.background_gate import background_task, busy
from stores import jobs_store, recipe_store


async def semantic_enricher_worker() -> None:
    if not SEMANTIC_ENRICHER_ENABLED:
        print("[enricher] disabled")
        return
    if not semantic_enricher.GEMINI_API_KEY:
        print("[enricher] disabled: GEMINI_API_KEY is empty")
        return

    await asyncio.sleep(60)
    print(
        f"[enricher] started (idle={SEMANTIC_ENRICHER_IDLE_SECONDS}s, "
        f"models={','.join(semantic_enricher.SEMANTIC_ENRICHER_MODELS)})"
    )

    while True:
        try:
            if is_active(SEMANTIC_ENRICHER_IDLE_SECONDS):
                await asyncio.sleep(60)
                continue
            if jobs_store.list_pending():
                await asyncio.sleep(60)
                continue
            if busy():
                await asyncio.sleep(30)
                continue

            candidates = [
                r for r in recipe_store.get_all()
                if semantic_enricher.needs_enrichment(r)
            ]
            if not candidates:
                await asyncio.sleep(SEMANTIC_ENRICHER_INTERVAL_SECONDS)
                continue

            recipe = candidates[0]
            async with background_task("semantic_enricher"):
                # Повторная проверка после получения блокировки.
                if is_active(SEMANTIC_ENRICHER_IDLE_SECONDS) or jobs_store.list_pending():
                    await asyncio.sleep(1)
                    continue
                result = await semantic_enricher.enrich_one(recipe)
            if result and result.get("status") == "quota_wait":
                await asyncio.sleep(max(60.0, min(3600.0, float(result.get("wait") or 60))))
            else:
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[enricher] error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(300)
