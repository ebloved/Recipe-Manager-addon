"""LLM cascade (v3.5.5) — единый маршрут для всех LLM-операций.

Линейная цепочка:
  1. user Orca
  2. user Custom (OpenAI-совместимый)
  3. user Gemini
  4. admin Gemini  (5 RPD)
  5. admin Hermes  (5 RPD)

Admin Orca НИКОГДА не используется.
RPD списывается один раз за проход (первый admin-провайдер).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def call_llm_cascade(
    *,
    user_id: str | None,
    prompt: str,
    system: str | None,
    max_tokens: int,
    temperature: float,
    job_id: str | None = None,
) -> tuple[str, str]:
    from config import (
        GEMINI_API_KEY,
        MATCHER_EXTERNAL_ENABLED,
        MATCHER_EXTERNAL_URL,
    )
    from services.auth import users_store
    from services.rate_limiter import rate_limiter

    user_orca: str | None = None
    user_custom_url: str | None = None
    user_custom_key: str | None = None
    user_custom_model: str | None = None
    user_gemini: str | None = None
    if user_id:
        try:
            conf = users_store.get_llm_config(user_id) or {}
            user_orca = conf.get("orcarouter_api_key") or None
            user_custom_url = conf.get("external_llm_url") or None
            user_custom_key = conf.get("external_llm_key") or None
            user_custom_model = conf.get("external_llm_model") or None
            user_gemini = conf.get("gemini_api_key") or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cascade] read user config failed: %s", exc)

    attempts: list[dict[str, Any]] = []
    
    # 1. Custom AI (OpenAI-совместимый) — ставим первым
    if user_custom_url and user_custom_key:
        attempts.append({"name": "custom_llm",
                         "kwargs": {"base_url": user_custom_url, "api_key": user_custom_key,
                                    "model": user_custom_model},
                         "label": "custom (user key)", "rpd": False})
    else:
        print("[cascade] skipped custom: no url or key in user profile")

    # 2. OrcaRouter
    if user_orca:
        attempts.append({"name": "orcarouter", "kwargs": {"api_key": user_orca},
                         "label": "orca (user key)", "rpd": False})
    if user_gemini:
        attempts.append({"name": "gemini", "kwargs": {"api_key": user_gemini},
                         "label": "gemini (user key)", "rpd": False})
    if GEMINI_API_KEY:
        attempts.append({"name": "gemini", "kwargs": {"api_key": None},
                         "label": "gemini (admin key)", "rpd": True})
    if MATCHER_EXTERNAL_ENABLED and MATCHER_EXTERNAL_URL:
        attempts.append({"name": "hermes", "kwargs": {"api_key": None},
                         "label": "hermes (admin key)", "rpd": True})

    if not attempts:
        raise HTTPException(
            503,
            "Нет доступных LLM-провайдеров. Введите свой ключ в Кабинете "
            "или настройте admin-ключи в .env.",
        )

    errors: list[str] = []
    rpd_checked = False

    for att in attempts:
        if att["rpd"] and not rpd_checked:
            if user_id and not await rate_limiter.can_generate(user_id):
                if user_orca or user_custom_key or user_gemini:
                    raise HTTPException(
                        502,
                        "Ваши LLM-ключи не сработали, а резервный лимит "
                        f"исчерпан. Ошибки: {'; '.join(errors) or 'нет'}",
                    )
                raise HTTPException(
                    429,
                    "Достигнут лимит 5 бесплатных генераций в день. "
                    "Добавьте свой API-ключ в Кабинете.",
                )
            rpd_checked = True
        try:
            print(f"[cascade] trying {att['label']}")
            text = await _call_provider(
                name=att["name"], kwargs=att["kwargs"],
                prompt=prompt, system=system, max_tokens=max_tokens,
                temperature=temperature, job_id=job_id,
            )
            if not text:
                raise RuntimeError("empty response")
            print(f"[cascade] ✓ {att['label']} ok")
            return text, att["name"]
        except Exception as exc:  # noqa: BLE001
            msg = str(exc) or type(exc).__name__
            errors.append(f"{att['label']}: {msg}")
            logger.warning("[cascade] %s failed: %s", att["label"], msg)
            continue

    raise HTTPException(502, f"All LLM providers failed: {'; '.join(errors)}")


async def _call_provider(
    *, name: str, kwargs: dict[str, Any], prompt: str,
    system: str | None, max_tokens: int, temperature: float,
    job_id: str | None,
) -> str:
    if name == "orcarouter":
        from services.orcarouter import orcarouter
        return await orcarouter.complete(
            prompt=prompt, system=system, max_tokens=max_tokens,
            temperature=temperature, job_id=job_id, api_key=kwargs.get("api_key"),
        )
    if name == "custom_llm":
        from services.custom_llm import CustomLLMProvider
        prov = CustomLLMProvider(
            base_url=kwargs["base_url"], api_key=kwargs["api_key"],
            model=kwargs.get("model"),
        )
        return await prov.complete(
            prompt=prompt, system=system, max_tokens=max_tokens,
            temperature=temperature, job_id=job_id,
        )
    if name == "gemini":
        from services.matcher.gemini_embedder import gemini_embedder
        return await gemini_embedder.complete(
            prompt=prompt, system=system, max_tokens=max_tokens,
            temperature=temperature, job_id=job_id, api_key=kwargs.get("api_key"),
        )
    if name == "hermes":
        from services.matcher.external_llm import external_llm
        return await external_llm.complete(
            prompt=prompt, system=system, max_tokens=max_tokens,
            temperature=temperature, job_id=job_id, api_key=kwargs.get("api_key"),
        )
    raise RuntimeError(f"Unknown provider: {name}")
