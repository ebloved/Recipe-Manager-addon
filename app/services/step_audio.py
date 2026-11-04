"""Аудио шагов рецепта: один MP3 на шаг, с дневным лимитом Gemini TTS."""
from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from db import SessionLocal
from services import voice_tts
from stores.db_models import RecipeStepAudio
from stores.settings import settings_store

_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_USAGE_KEY = "tts_usage_v1"
_LOCK = asyncio.Lock()


class StepAudioError(RuntimeError):
    """Ошибка озвучки шага с кодом и моделью для аудита/UI."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int = 409,
        provider: str | None = None,
        model: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.provider = provider
        self.model = model
        self.details = details or {}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _usage() -> dict[str, Any]:
    raw = settings_store.get(_USAGE_KEY) or {}
    if not isinstance(raw, dict) or raw.get("date") != _today():
        raw = {"date": _today(), "count": 0}
    return raw


def usage() -> dict[str, Any]:
    data = _usage()
    return {
        "date": data["date"],
        "count": int(data.get("count") or 0),
        "limit": int(settings_store.get("tts_daily_limit", 10) or 10),
        "enabled": bool(settings_store.get("tts_enabled", False)),
    }


async def _increment_usage() -> None:
    data = _usage()
    data["count"] = int(data.get("count") or 0) + 1
    await settings_store.set(_USAGE_KEY, data)


def step_text(recipe: dict[str, Any], index: int) -> str | None:
    steps = recipe.get("instructions") or []
    if index < 0 or index >= len(steps):
        return None
    text = " ".join(str(steps[index] or "").split()).strip()
    return text or None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audio_url(audio_hash: str) -> str:
    return f"/api/voice/audio/{audio_hash}.mp3"


def audio_path(audio_hash: str) -> Path | None:
    if not _HASH_RE.fullmatch(audio_hash or ""):
        return None
    path = voice_tts.TTS_DIR / f"{audio_hash}.mp3"
    return path if path.is_file() else None


def _row_dict(row: RecipeStepAudio) -> dict[str, Any]:
    return {
        "step_index": row.step_index,
        "text_hash": row.text_hash,
        "audio_hash": row.audio_hash,
        "url": audio_url(row.audio_hash),
        "model": row.model,
        "voice": row.voice,
        "duration": row.duration,
    }


async def list_for_recipe(recipe_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(RecipeStepAudio)
                .where(RecipeStepAudio.recipe_id == recipe_id)
                .order_by(RecipeStepAudio.step_index, RecipeStepAudio.created_at.desc())
            )
        ).scalars().all()
    seen: dict[int, RecipeStepAudio] = {}
    for row in rows:
        seen.setdefault(row.step_index, row)
    return [_row_dict(row) for _, row in sorted(seen.items())]


async def get_or_create(
    recipe: dict[str, Any], index: int, *, allow_generate: bool = True
) -> dict[str, Any]:
    text = step_text(recipe, index)
    if not text:
        raise StepAudioError(
            "Шаг рецепта не найден.",
            code="step_not_found",
            status_code=404,
        )
    th = text_hash(text)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(RecipeStepAudio).where(
                    RecipeStepAudio.recipe_id == recipe.get("id"),
                    RecipeStepAudio.step_index == index,
                    RecipeStepAudio.text_hash == th,
                )
            )
        ).scalar_one_or_none()
        if row and audio_path(row.audio_hash):
            return _row_dict(row)
    if not allow_generate:
        raise StepAudioError(
            "Аудио шага ещё не сгенерировано.",
            code="tts_not_generated",
            status_code=404,
        )

    async with _LOCK:
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(RecipeStepAudio).where(
                        RecipeStepAudio.recipe_id == recipe.get("id"),
                        RecipeStepAudio.step_index == index,
                        RecipeStepAudio.text_hash == th,
                    )
                )
            ).scalar_one_or_none()
            if row and audio_path(row.audio_hash):
                return _row_dict(row)

        cached = voice_tts.cache_file(text)
        if cached.is_file():
            audio = cached.read_bytes()
            cached_flag = True
            model = "cache"
        else:
            if not bool(settings_store.get("tts_enabled", False)):
                raise StepAudioError(
                    "Озвучка отключена в админке.",
                    code="tts_disabled",
                    status_code=409,
                )
            limit = int(settings_store.get("tts_daily_limit", 10) or 10)
            used = int(_usage().get("count") or 0)
            if used >= limit:
                raise StepAudioError(
                    f"Дневной лимит озвучки исчерпан: {used}/{limit}.",
                    code="tts_daily_limit",
                    status_code=429,
                    provider="local",
                    details={"used": used, "limit": limit},
                )
            try:
                audio, cached_flag, model = await voice_tts.synthesize_ex(text)
            except voice_tts.TTSError as exc:
                is_quota = exc.status_code == 429
                if is_quota:
                    message = (
                        "Gemini TTS: слишком много запросов (429). "
                        "Лимит Gemini исчерпан или превышен."
                    )
                    if exc.model:
                        message += f" Модель: {exc.model}."
                    code = "tts_quota"
                    status_code = 429
                else:
                    message = "Gemini TTS: ошибка"
                    if exc.status_code:
                        message += f" ({exc.status_code})"
                    message += "."
                    if exc.model:
                        message += f" Модель: {exc.model}."
                    message += f" {str(exc)[:500]}"
                    code = "tts_error"
                    status_code = 502
                raise StepAudioError(
                    message,
                    code=code,
                    status_code=status_code,
                    provider=exc.provider,
                    model=exc.model,
                    details={
                        "models_tried": exc.attempts,
                        "voice": "Ludo",
                        "usage": usage(),
                    },
                ) from exc
            if not cached_flag:
                await _increment_usage()

        audio_hash = voice_tts.cache_key(text)
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(RecipeStepAudio).where(
                        RecipeStepAudio.recipe_id == recipe.get("id"),
                        RecipeStepAudio.step_index == index,
                        RecipeStepAudio.text_hash == th,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = RecipeStepAudio(
                    id=uuid.uuid4().hex,
                    recipe_id=str(recipe.get("id")),
                    step_index=index,
                    text_hash=th,
                    audio_hash=audio_hash,
                    model=model,
                    voice="Ludo",
                    duration=None,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(row)
            else:
                row.audio_hash = audio_hash
                row.model = model
            await session.commit()
            return _row_dict(row)


async def first_missing() -> tuple[dict[str, Any], int] | None:
    from stores import recipe_store

    async with SessionLocal() as session:
        rows = (await session.execute(select(RecipeStepAudio))).scalars().all()
    have = {(r.recipe_id, r.step_index, r.text_hash) for r in rows}
    for recipe in recipe_store.get_all():
        rid = str(recipe.get("id") or "")
        steps = recipe.get("instructions") or []
        for index, step in enumerate(steps):
            text = " ".join(str(step or "").split()).strip()
            if text and (rid, index, text_hash(text)) not in have:
                return recipe, index
    return None
