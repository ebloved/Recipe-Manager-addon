"""Оркестратор генерации рецептов."""
from __future__ import annotations

import logging
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from recipe_manager.importer import parse_markdown_recipe
from config import GEMINI_MODELS, GENERATOR_MAX_TOKENS
from stores import gen_profiles_store, recipe_store

from .prompt import build_prompt
from .providers import get_llm_provider

logger = logging.getLogger(__name__)

_LAST_ATTEMPT: dict[str, Any] = {}

def _record_attempt(**kwargs: Any) -> None:
    _LAST_ATTEMPT.clear(); _LAST_ATTEMPT.update(kwargs)

def get_last_attempt() -> dict[str, Any]:
    return dict(_LAST_ATTEMPT)


_SPLIT_RE = re.compile(r"\n\s*-{3,}\s*SPLIT\s*-{3,}\s*\n", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_md(raw: str) -> str:
    """Убирает ``` вокруг ответа и чинит формат перед парсингом."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
    s = s.strip()

    # Auto-heal: LLM иногда пишет текст перед YAML — режем до первого ---
    if not s.startswith("---") and not s.startswith("#"):
        idx = s.find("---")
        if idx > 0:
            s = s[idx:]

    # Auto-heal: Gemini иногда пишет "item:" вместо "name:" в ингредиентах
    s = re.sub(r"^(\s*)-(\s*)item:", r"\1-\2name:", s, flags=re.MULTILINE)

    # Auto-heal description/title: quote values containing ': ' (YAML scanner)
    def _quote_colon(m):
        prefix = m.group(1)
        val = m.group(2).strip()
        if not (val.startswith('"') or val.startswith("'")):
            val = val.replace('"', '\\"')
            return prefix + '"' + val + '"'
        return m.group(0)

    s = re.sub(
        r'^(description:\s+)([^"\n][^\n]*:\s+[^\n]*)$',
        _quote_colon, s, flags=re.MULTILINE,
    )
    s = re.sub(
        r'^(title:\s+)([^"\n][^\n]*:\s+[^\n]*)$',
        _quote_colon, s, flags=re.MULTILINE,
    )

    # Auto-heal inline lists: tags: [a, b, c] -> tags: ["a", "b", "c"]
    def _quote_flow(m):
        prefix = m.group(1)
        items = [x.strip() for x in m.group(2).split(",") if x.strip()]
        if not items:
            return prefix + "[]"
        quoted = ", ".join('"' + x + '"' for x in items)
        return prefix + "[" + quoted + "]"

    s = re.sub(r'^(\w+:\s*)\[([^\]]+)\]', _quote_flow, s, flags=re.MULTILINE)

    # Невидимые пробелы/ZWSP
    s = s.replace(chr(160), " ").replace(chr(0x200b), "")

    return s.strip()


def _pick_samples(profile: dict[str, Any] | None, n: int) -> list[dict[str, Any]]:
    """Возвращает до N рецептов-образцов, предпочитая подходящие под профиль."""
    if n <= 0:
        return []
    all_recipes = recipe_store.get_all()
    if not all_recipes:
        return []

    if not profile:
        return random.sample(all_recipes, min(n, len(all_recipes)))

    c = profile.get("constraints") or {}
    max_cal = c.get("max_calories_per_serving")
    max_total = c.get("max_total_time_min")

    def fits(r: dict[str, Any]) -> bool:
        if max_cal is not None:
            cal = ((r.get("nutrition") or {}).get("calories"))
            try:
                if cal is not None and float(cal) > float(max_cal):
                    return False
            except (TypeError, ValueError):
                pass
        if max_total is not None:
            total = r.get("total_time") or r.get("time") or (
                (r.get("prep_time") or 0) + (r.get("cook_time") or 0)
            )
            try:
                if total and float(total) > float(max_total):
                    return False
            except (TypeError, ValueError):
                pass
        return True

    matching = [r for r in all_recipes if fits(r)]
    if len(matching) >= n:
        return random.sample(matching, n)

    rest = [r for r in all_recipes if r not in matching]
    random.shuffle(rest)
    result = matching + rest
    return result[:n]


def _model_name(provider: Any) -> str:
    if getattr(provider, "name", None) == "gemini" and GEMINI_MODELS:
        return GEMINI_MODELS[0]
    for attr in ("model", "chat_model", "model_key"):
        v = getattr(provider, attr, None)
        if v:
            return str(v)
    return ""


async def generate_suggestions(
    *,
    profile_id: str | None,
    topic: str | None,
    count: int,
    samples_count: int,
    max_count: int = 5,
    samples_max: int = 10,
) -> list[dict[str, Any]]:
    """Генерирует рецепты через каскад провайдеров."""
    from services.activity import touch
    touch()
    count = max(1, min(int(count or 1), int(max_count)))
    samples_count = max(0, min(int(samples_count or 0), int(samples_max)))

    if profile_id:
        profile = gen_profiles_store.get(profile_id)
        if not profile or profile.get("deleted"):
            raise HTTPException(404, f"Profile {profile_id} not found")
    else:
        profile = gen_profiles_store.get_active()

    provider, provider_name = get_llm_provider()
    if provider is None:
        raise HTTPException(
            503,
            "Нет доступных LLM-провайдеров. "
            "Настройте matcher_external_* или GEMINI_API_KEY в конфиге.",
        )

    samples = _pick_samples(profile, samples_count)
    system, user = build_prompt(profile, samples, topic, count)

    logger.info(
        "[generator] provider=%s, count=%d, samples=%d, profile=%s",
        provider_name, count, len(samples), (profile or {}).get("name"),
    )

    import time as _time
    _t0 = _time.monotonic()
    try:
        raw_response = await provider.complete(
            prompt=user, system=system,
            max_tokens=GENERATOR_MAX_TOKENS, temperature=0.7,
        )
    except Exception as exc:  # noqa: BLE001
        _elapsed = round(_time.monotonic() - _t0, 2)
        _usage = getattr(provider, "_last_usage", None) or {}
        _record_attempt(status="error", provider=provider_name,
                        model=_model_name(provider), elapsed_s=_elapsed,
                        error=str(exc)[:300], at=_now(),
                        usage=_usage)
        logger.warning("[generator] provider %s failed (%.1fs): %s",
                       provider_name, _elapsed, exc)
        raise HTTPException(502, f"LLM вернул ошибку: {exc}") from exc
    _elapsed = round(_time.monotonic() - _t0, 2)
    _usage = getattr(provider, "_last_usage", None) or {}
    _record_attempt(status="ok", provider=provider_name,
                    model=_model_name(provider), elapsed_s=_elapsed,
                    error=None, at=_now(),
                    finish_reason=_usage.get("finish_reason"),
                    usage=_usage)  # весь объект: attempts, models_tried, usage

    raw_response = _clean_md(raw_response)
    if not raw_response:
        raise HTTPException(502, "LLM вернул пустой ответ")

    if count > 1 and _SPLIT_RE.search(raw_response):
        parts = _SPLIT_RE.split(raw_response)
    else:
        parts = [raw_response]

    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        raise HTTPException(502, "Не удалось разбить ответ на рецепты")

    model_name = _model_name(provider)

    results: list[dict[str, Any]] = []
    for md in parts:
        suggestion: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "status": "pending",
            "created_at": _now(),
            "profile_id": (profile or {}).get("id"),
            "profile_name": (profile or {}).get("name"),
            "topic": topic.strip() if topic else None,
            "provider": provider_name,
            "model": model_name,
            "markdown": md,
            "recipe_data": None,
            "error": None,
        }
        try:
            parsed = parse_markdown_recipe(md)
            suggestion["recipe_data"] = parsed
        except Exception as exc:  # noqa: BLE001
            suggestion["error"] = f"parse_failed: {exc}"
        results.append(suggestion)

    return results
