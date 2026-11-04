"""Фоновая озвучка шагов рецептов."""
from __future__ import annotations

import asyncio

from services import step_audio
from services.activity import is_active
from services.background_gate import background_task, busy
from stores import jobs_store
from stores.settings import settings_store


async def step_audio_worker() -> None:
    await asyncio.sleep(60)
    print("[tts] step audio worker started")
    while True:
        try:
            if not bool(settings_store.get("tts_enabled", False)):
                await asyncio.sleep(60)
                continue
            if is_active(600) or jobs_store.list_pending() or busy():
                await asyncio.sleep(60)
                continue
            missing = await step_audio.first_missing()
            if not missing:
                await asyncio.sleep(300)
                continue
            recipe, index = missing
            async with background_task("step_audio"):
                try:
                    item = await step_audio.get_or_create(recipe, index)
                    print(f"[tts] {recipe.get('name')!r} step {index + 1}: {item.get('url')}")
                except step_audio.StepAudioError as exc:
                    if "daily limit" in str(exc):
                        print("[tts] daily limit reached")
                        await asyncio.sleep(3600)
                        continue
                    print(f"[tts] skip {recipe.get('name')!r} step {index + 1}: {exc}")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[tts] error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(300)
