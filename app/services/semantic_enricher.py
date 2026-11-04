"""Семантическое обогащение рецептов через бесплатные Gemini Lite.

Работает только на админском ключе, по одному рецепту, с отдельными
лимитами по каждой модели. Заполняет только пустые поля.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from config import (
    GEMINI_API_KEY,
    SEMANTIC_ENRICHER_ENABLED,
    SEMANTIC_ENRICHER_MODELS,
)
from services.recipe_standard import source_hash
from stores import recipe_store
from stores.settings import settings_store

_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_STATE_KEY = "semantic_enricher_quota_v1"
_MODEL_LIMITS = {"rpm": 15, "rpd": 500}
_MIN_INTERVAL = 4.2  # 15 RPM
_TARGETS = (
    "description", "tags", "courses", "categories",
    "collections", "cuisine", "category", "nutrition",
)

_LAST_RESULT: dict[str, Any] = {}


class EnricherError(RuntimeError):
    pass


class QuotaExhausted(EnricherError):
    pass


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _state() -> dict[str, Any]:
    raw = settings_store.get(_STATE_KEY) or {}
    if not isinstance(raw, dict) or raw.get("date") != _today():
        raw = {"date": _today(), "models": {}}
    raw.setdefault("models", {})
    return raw


async def _save_state(state: dict[str, Any]) -> None:
    await settings_store.set(_STATE_KEY, state)


def _model_state(state: dict[str, Any], model: str) -> dict[str, Any]:
    models = state.setdefault("models", {})
    return models.setdefault(model, {"count": 0, "last_ts": 0.0, "cooldown_until": 0.0})


def _choose_model() -> tuple[str | None, float]:
    """Возвращает (model, seconds_to_wait)."""
    if not GEMINI_API_KEY:
        return None, 3600.0
    state = _state()
    now = _now_ts()
    best: tuple[str, int] | None = None
    shortest_wait = 3600.0
    for model in SEMANTIC_ENRICHER_MODELS:
        ms = _model_state(state, model)
        if ms.get("count", 0) >= _MODEL_LIMITS["rpd"]:
            continue
        if now < float(ms.get("cooldown_until") or 0):
            shortest_wait = min(shortest_wait, float(ms["cooldown_until"]) - now)
            continue
        wait = max(0.0, float(ms.get("last_ts") or 0) + _MIN_INTERVAL - now)
        if wait > 0:
            shortest_wait = min(shortest_wait, wait)
            continue
        if best is None or int(ms.get("count", 0)) < best[1]:
            best = (model, int(ms.get("count", 0)))
    return (best[0] if best else None), shortest_wait


async def _mark_used(model: str) -> None:
    state = _state()
    ms = _model_state(state, model)
    ms["count"] = int(ms.get("count", 0)) + 1
    ms["last_ts"] = _now_ts()
    await _save_state(state)


async def _mark_429(model: str) -> None:
    state = _state()
    ms = _model_state(state, model)
    ms["cooldown_until"] = _now_ts() + 60.0
    await _save_state(state)


def _content_hash(recipe: dict[str, Any]) -> str:
    payload = {
        "name": recipe.get("name"),
        "ingredients": recipe.get("ingredients"),
        "instructions": recipe.get("instructions"),
        "servings": recipe.get("servings"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def needs_enrichment(recipe: dict[str, Any]) -> bool:
    if not recipe.get("ingredients") or not recipe.get("instructions"):
        return False
    if recipe.get("enrichment_hash") == _content_hash(recipe):
        return False
    for field in _TARGETS:
        value = recipe.get(field)
        if field == "nutrition":
            if not value:
                return True
        elif field in ("tags", "courses", "categories", "collections"):
            if not value:
                return True
        elif not str(value or "").strip():
            return True
    return False


def _clean_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = re.sub(r"\s+", " ", str(item)).strip().lower()
        text = text.strip(" .,:;")
        if not text or len(text) > 40 or text in out:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_str(value: Any, *, limit: int = 60) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] or None


def _clean_nutrition(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    allowed = (
        "calories", "protein", "fat", "carbohydrates",
        "fiber", "sugar", "sodium",
    )
    out: dict[str, float] = {}
    for key in allowed:
        raw = value.get(key)
        if raw is None or raw == "":
            continue
        try:
            num = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if 0 <= num <= 10000:
            out[key] = round(num, 1)
    return out or None


def _parse_json(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    data = json.loads(s)
    if not isinstance(data, dict):
        raise EnricherError("LLM returned non-object JSON")
    return data


def _prompt(recipe: dict[str, Any]) -> str:
    ings = []
    for ing in recipe.get("ingredients") or []:
        if isinstance(ing, dict):
            name = ing.get("name") or ""
            amount = ing.get("amount")
            unit = ing.get("unit")
            notes = ing.get("notes")
            line = " ".join(str(x) for x in (amount, unit, name) if x)
            if notes:
                line += f" ({notes})"
            ings.append(line)
        else:
            ings.append(str(ing))
    steps = "\n".join(
        f"{i}. {s}" for i, s in enumerate(recipe.get("instructions") or [], 1)
    )
    return (
        f"Название: {recipe.get('name') or ''}\n"
        f"Описание: {recipe.get('description') or ''}\n"
        f"Порции: {recipe.get('servings') or 'не указаны'}\n"
        f"Ингредиенты:\n" + "\n".join(f"- {x}" for x in ings) + "\n\n"
        f"Шаги:\n{steps}\n\n"
        "Заполни только отсутствующие поля. Не переписывай ингредиенты и шаги.\n"
        "Верни строго JSON:\n"
        "{\n"
        '  "description": "1–2 предложения",\n'
        '  "tags": ["тег"],\n'
        '  "courses": ["суп"],\n'
        '  "categories": ["домашняя еда"],\n'
        '  "collections": ["быстрые рецепты"],\n'
        '  "cuisine": "европейская",\n'
        '  "category": "суп",\n'
        '  "nutrition": {"calories": 0, "protein": 0, "fat": 0, '
        '"carbohydrates": 0, "fiber": 0, "sugar": 0, "sodium": 0}\n'
        "}\n"
        "Правила: tags — 3–8 коротких тегов; courses/categories/collections — "
        "до 3; nutrition — оценка на одну порцию, если данных достаточно, иначе null."
    )


_SYSTEM = (
    "Ты — кулинарный редактор. Верни только валидный JSON без markdown. "
    "Не выдумывай ингредиенты и шаги. Пиши по-русски."
)


async def _call_model(model: str, recipe: dict[str, Any]) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise EnricherError("GEMINI_API_KEY не задан")
    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": _prompt(recipe)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _API.format(model=model),
            params={"key": GEMINI_API_KEY},
            json=payload,
        )
    if resp.status_code == 429:
        await _mark_429(model)
        raise QuotaExhausted(f"429 for {model}")
    if resp.status_code >= 400:
        raise EnricherError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        raw = "".join(str(p.get("text") or "") for p in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise EnricherError(f"bad Gemini response: {str(data)[:200]}") from exc
    return _parse_json(raw)


async def enrich_one(recipe: dict[str, Any]) -> dict[str, Any] | None:
    """Обогащает один рецепт. Возвращает патч или None."""
    global _LAST_RESULT
    if not SEMANTIC_ENRICHER_ENABLED or not needs_enrichment(recipe):
        return None
    model, wait = _choose_model()
    if not model:
        if wait < 3600:
            return {"status": "quota_wait", "wait": round(wait, 1)}
        return {"status": "quota_exhausted"}

    await _mark_used(model)
    try:
        data = await _call_model(model, recipe)
    except QuotaExhausted as exc:
        _LAST_RESULT = {"status": "429", "model": model, "error": str(exc)}
        return {"status": "quota_wait", "wait": 60}
    except Exception as exc:  # noqa: BLE001
        _LAST_RESULT = {"status": "error", "model": model, "error": str(exc)[:300]}
        return {"status": "error", "error": str(exc)[:300]}

    patch: dict[str, Any] = {}
    if not str(recipe.get("description") or "").strip():
        desc = _clean_str(data.get("description"), limit=300)
        if desc and len(desc) >= 15:
            patch["description"] = desc
    for field, limit in (
        ("tags", 10), ("courses", 5), ("categories", 5), ("collections", 5),
    ):
        if not recipe.get(field):
            values = _clean_list(data.get(field), limit=limit)
            if values:
                patch[field] = values
    for field in ("cuisine", "category"):
        if not str(recipe.get(field) or "").strip():
            value = _clean_str(data.get(field), limit=60)
            if value:
                patch[field] = value
    if not recipe.get("nutrition"):
        nutrition = _clean_nutrition(data.get("nutrition"))
        if nutrition:
            patch["nutrition"] = nutrition
            patch["nutrition_source"] = "ai_estimate"

    patch["enrichment_hash"] = _content_hash(recipe)
    patch["enrichment_source"] = model
    patch["enrichment_at"] = datetime.now(timezone.utc).isoformat()
    updated = await recipe_store.patch_if_unchanged(
        recipe.get("id"), source_hash(recipe), patch
    )
    _LAST_RESULT = {
        "status": "ok" if updated else "changed",
        "model": model,
        "fields": sorted(k for k in patch if k not in ("enrichment_hash", "enrichment_source", "enrichment_at")),
    }
    if updated:
        print(f"[enricher] {str(recipe.get('id'))[:8]} {recipe.get('name')!r} -> {model} {_LAST_RESULT['fields']}")
    return patch if updated else None


def status() -> dict[str, Any]:
    state = _state()
    models = {}
    for model in SEMANTIC_ENRICHER_MODELS:
        ms = _model_state(state, model)
        models[model] = {
            "used_today": int(ms.get("count", 0)),
            "limit_rpd": _MODEL_LIMITS["rpd"],
            "cooldown_until": ms.get("cooldown_until", 0),
        }
    return {
        "enabled": SEMANTIC_ENRICHER_ENABLED,
        "admin_key": bool(GEMINI_API_KEY),
        "models": models,
        "last": _LAST_RESULT,
    }
