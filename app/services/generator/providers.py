"""Реестр LLM-провайдеров для генератора.

Использует существующие объекты из services/matcher:
- external_llm (OpenAI-совместимый, Hermes)
- gemini_embedder (Gemini)

Оба класса реализуют метод complete(prompt, system, max_tokens, temperature).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import (
    GEMINI_API_KEY,
    GEMINI_MODELS,
    MATCHER_EXTERNAL_ENABLED,
    MATCHER_EXTERNAL_URL,
)

logger = logging.getLogger(__name__)


@dataclass
class ProviderStatus:
    name: str
    available: bool
    model: str
    priority: int
    error: str | None = None


# Ленивые импорты: если matcher не собран, генератор просто не работает,
# но аддон запускается.
try:
    from services.matcher.external_llm import external_llm
except Exception as exc:  # noqa: BLE001
    external_llm = None  # type: ignore[assignment]
    logger.info("generator: external_llm недоступен: %s", exc)

try:
    from services.matcher.gemini_embedder import gemini_embedder
except Exception as exc:  # noqa: BLE001
    gemini_embedder = None  # type: ignore[assignment]
    logger.info("generator: gemini_embedder недоступен: %s", exc)


def _external_available() -> bool:
    return bool(
        external_llm is not None
        and MATCHER_EXTERNAL_ENABLED
        and MATCHER_EXTERNAL_URL
    )


def _gemini_available() -> bool:
    return bool(gemini_embedder is not None and GEMINI_API_KEY)


def _model_name(provider: Any) -> str:
    """Реально используемая модель: Gemini → GEMINI_MODELS[0], Hermes → chat_model."""
    if getattr(provider, "name", None) == "gemini" and GEMINI_MODELS:
        return GEMINI_MODELS[0]
    for attr in ("model", "chat_model", "model_key"):
        v = getattr(provider, attr, None)
        if v:
            return str(v)
    return "?"


def get_llm_provider() -> tuple[Any, str] | tuple[None, None]:
    """Возвращает (provider, provider_name) первого доступного.

    Порядок: external (Hermes) → gemini.
    """
    if _external_available():
        return external_llm, "hermes"
    if _gemini_available():
        return gemini_embedder, "gemini"
    return None, None


def get_providers_status() -> dict:
    """Информация для /api/generator/status."""
    providers = []

    if external_llm is not None:
        providers.append(ProviderStatus(
            name="hermes",
            available=_external_available(),
            model=_model_name(external_llm),
            priority=20,
            error=None if _external_available() else "disabled or not configured",
        ))

    if gemini_embedder is not None:
        providers.append(ProviderStatus(
            name="gemini",
            available=_gemini_available(),
            model=_model_name(gemini_embedder),
            priority=40,
            error=None if _gemini_available() else "GEMINI_API_KEY not set",
        ))

    providers.sort(key=lambda p: p.priority)

    active = None
    if _external_available():
        active = "hermes"
    elif _gemini_available():
        active = "gemini"

    return {
        "providers": [
            {
                "name": p.name,
                "available": p.available,
                "model": p.model,
                "priority": p.priority,
                "error": p.error,
            }
            for p in providers
        ],
        "active_provider": active,
    }
