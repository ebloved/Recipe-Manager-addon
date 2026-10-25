"""Оценка active_time рецепта через LLM.

Промпт: LLM получает шаги и для каждого возвращает JSON {index, active_min}.
Активное время — когда человек непосредственно занят готовкой (нарезка,
обжарка с помешиванием, формовка). Пассивное (тушение, выпечка, маринад,
настаивание) не считается.

Публичное API:
    estimate_active_time(recipe, force=False) -> dict
        Возвращает patch для recipe_store.update() с полями:
            active_time, active_time_estimated, active_time_hash, active_time_at
        или {"active_time_error": "..."} — если LLM недоступен.
        или {} — если hash не изменился и оценка уже есть (без force).

    hash_instructions(instructions) -> str
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from services.generator.providers import get_llm_provider

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Ты — эксперт по кулинарии. Отвечай СТРОГО валидным JSON без markdown и "
    "комментариев. Никаких ``` вокруг ответа, никакого текста до или после."
)

_PROMPT_TEMPLATE = (
    "Рецепт: {name}\n"
    "\n"
    "Шаги:\n"
    "{steps}\n"
    "\n"
    "Для каждого шага определи «активное» время в минутах — время, когда "
    "человек непосредственно занят готовкой (нарезка, помешивание при "
    "обжарке, формовка, взвешивание). Пассивные периоды (тушение под "
    "крышкой, выпечка в духовке, маринование, настаивание) НЕ считаются, "
    "даже если они указаны в шаге.\n"
    "\n"
    "Если шаг содержит только пассивное время — active_min: 0.\n"
    "Если время в шаге не указано, оцени типичное значение.\n"
    "\n"
    "Верни строго JSON:\n"
    '{{"steps": [{{"index": 1, "active_min": 5}}, ...], "total_active_min": 15}}\n'
)


def hash_instructions(instructions: list[Any]) -> str:
    """SHA256 от JSON-нормализованного списка шагов. Стабилен при перестановке."""
    if not instructions:
        return hashlib.sha256(b"[]").hexdigest()
    norm = [str(s).strip() for s in instructions]
    return hashlib.sha256(
        json.dumps(norm, ensure_ascii=False, sort_keys=False).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_prompt(recipe: dict[str, Any]) -> str:
    steps_lines = []
    for i, step in enumerate(recipe.get("instructions") or [], 1):
        steps_lines.append(f"{i}. {step}")
    steps = "\n".join(steps_lines) if steps_lines else "(нет шагов)"
    return _PROMPT_TEMPLATE.format(name=recipe.get("name") or "—", steps=steps)


def _parse_json(raw: str) -> dict[str, Any]:
    """Парсит JSON, снимая возможные ```-обёртки."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
        s = s.strip()
    # Иногда LLM добавляет пояснение до {. Обрежем до первой {.
    idx = s.find("{")
    if idx > 0:
        s = s[idx:]
    end = s.rfind("}")
    if end >= 0:
        s = s[: end + 1]
    return json.loads(s)


async def estimate_active_time(
    recipe: dict[str, Any], force: bool = False
) -> dict[str, Any]:
    """Возвращает patch для recipe_store.update().

    Логика:
    - Нет instructions → {active_time: 0, estimated: false} (мгновенно).
    - Hash совпадает и active_time есть и не force → {} (нечего делать).
    - Иначе: вызвать LLM, распарсить JSON, вернуть patch.
    - При ошибке LLM → {"active_time_error": "..."} — рецепт сохраняется
      с ошибкой, вызывающая сторона решает, показывать ли.
    """
    instructions = recipe.get("instructions") or []
    if not instructions:
        return {
            "active_time": 0,
            "active_time_estimated": False,
            "active_time_hash": None,
            "active_time_at": _now(),
        }

    h = hash_instructions(instructions)

    if not force and recipe.get("active_time_hash") == h and recipe.get("active_time") is not None:
        return {}

    provider, provider_name = get_llm_provider()
    if provider is None:
        return {"active_time_error": "no_provider"}

    prompt = _build_prompt(recipe)
    logger.info(
        "[active_time] estimating %r: %d steps, provider=%s",
        (recipe.get("name") or "—")[:50],
        len(instructions),
        provider_name,
    )

    try:
        # v1.9.2: thinking-модели тратят max_output_tokens на reasoning.
        # 2000 не хватает — модель уходит в incomplete/in_progress надолго.
        # Ответ короткий (JSON с числами), 8000 с запасом.
        raw = await provider.complete(
            prompt=prompt,
            system=_SYSTEM,
            max_tokens=8000,
            temperature=0.1,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[active_time] LLM failed: %s", exc)
        return {"active_time_error": str(exc)[:200]}

    try:
        data = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("[active_time] JSON parse failed: %s, raw=%.200s", exc, raw)
        return {"active_time_error": f"json_parse: {exc}"}

    try:
        total = int(data.get("total_active_min") or 0)
        if total < 0:
            total = 0
    except (TypeError, ValueError):
        return {"active_time_error": "bad total_active_min"}

    logger.info(
        "[active_time] %r → %d min (provider=%s)",
        (recipe.get("name") or "—")[:50],
        total,
        provider_name,
    )
    return {
        "active_time": total,
        "active_time_estimated": True,
        "active_time_hash": h,
        "active_time_at": _now(),
        "active_time_error": None,
    }
