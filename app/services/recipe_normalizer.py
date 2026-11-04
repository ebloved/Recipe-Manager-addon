"""Нормализация рецепта к стандарту (детерминированная часть)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from services.recipe_linter import lint_recipe
from services.recipe_standard import (
    SCHEMA_VERSION,
    dedupe_ingredients,
    normalize_ingredient,
    normalize_list,
    servings_text as make_servings_text,
    source_hash,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _normalize_instructions(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        raw = [line.strip() for line in value.splitlines() if line.strip()]
    elif isinstance(value, list):
        raw = [str(item).strip() for item in value if str(item).strip()]
    else:
        raw = [str(value).strip()]
    return raw


def _expand_comma_ingredients(raw: Any) -> list[Any]:
    """Разбивает "Соль, перец, багет" на отдельные ингредиенты.

    Только если у ингредиента нет количества/единицы — иначе запятая
    может быть частью нормального названия.
    """
    if isinstance(raw, dict):
        name = str(raw.get("name") or "")
        if raw.get("amount") is None and raw.get("unit") is None and "," in name:
            parts = [part.strip() for part in name.split(",") if part.strip()]
            if len(parts) > 1:
                return [{**raw, "name": part} for part in parts]
    return [raw]


def normalize_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Возвращает новый рецепт, приведённый к стандарту.

    Не делает LLM-вызовов и не сохраняет результат.
    """
    out = copy.deepcopy(recipe)

    out["name"] = str(out.get("name") or out.get("title") or "").strip()
    out["description"] = (str(out.get("description") or "").strip() or None)

    ingredients: list[dict[str, Any]] = []
    for raw in out.get("ingredients") or []:
        for expanded in _expand_comma_ingredients(raw):
            item = normalize_ingredient(expanded)
            if item.get("name") or item.get("is_heading"):
                ingredients.append(item)
    out["ingredients"] = dedupe_ingredients(ingredients)

    out["instructions"] = _normalize_instructions(out.get("instructions"))

    prep = _int_or_none(out.get("prep_time"))
    cook = _int_or_none(out.get("cook_time"))
    out["prep_time"] = prep
    out["cook_time"] = cook
    if prep is not None and cook is not None:
        out["total_time"] = prep + cook
    else:
        out["total_time"] = _int_or_none(out.get("total_time"))

    servings = _int_or_none(out.get("servings"))
    out["servings"] = servings
    current_servings_text = str(out.get("servings_text") or "").strip()
    if not current_servings_text or current_servings_text.isdigit():
        current_servings_text = make_servings_text(servings)
    out["servings_text"] = current_servings_text

    for key in ("tags", "courses", "categories", "collections"):
        out[key] = normalize_list(out.get(key))

    for key in ("cuisine", "category"):
        value = out.get(key)
        out[key] = str(value).strip().lower() if value else None

    nutrition = out.get("nutrition")
    if isinstance(nutrition, dict):
        out["nutrition"] = {
            str(k): v for k, v in nutrition.items()
            if v not in (None, "")
        }
    else:
        out["nutrition"] = None

    out["notes"] = (str(out.get("notes") or "").strip() or None)

    # Старые auth-ошибки active_time (например, после ротации ключа) не
    # являются проблемой рецепта: снимаем их, чтобы не держать ложный warning.
    active_error = str(out.get("active_time_error") or "")
    if active_error and ("401" in active_error or "API key not valid" in active_error):
        out["active_time_error"] = None

    out["schema_version"] = SCHEMA_VERSION
    out["normalized_at"] = _now()
    out["normalization_hash"] = source_hash(out)
    out["normalization_issues"] = lint_recipe(out, check_roundtrip=True)
    severities = {i.get("severity") for i in out["normalization_issues"]}
    out["normalization_status"] = (
        "issues" if severities & {"error", "warning"} else "ok"
    )
    out["normalization_error"] = None
    return out


def needs_normalization(recipe: dict[str, Any]) -> bool:
    if recipe.get("schema_version") != SCHEMA_VERSION:
        return True
    if not recipe.get("normalization_hash"):
        return True
    return recipe.get("normalization_hash") != source_hash(recipe)
