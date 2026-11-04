"""Linter рецептов: быстрые детерминированные проверки по стандарту."""
from __future__ import annotations

from typing import Any

from services.recipe_standard import (
    CANONICAL_UNITS,
    SCHEMA_VERSION,
    normalize_ingredient,
    normalize_list,
)

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _issue(code: str, severity: str, field: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def _ingredient_key(item: dict[str, Any]) -> tuple[str, str]:
    from services.shopping_normalizer import normalize_for_connector
    return (
        normalize_for_connector(item.get("name") or ""),
        (item.get("unit") or "").lower(),
    )


def _lint_ingredients(ingredients: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(ingredients, list) or not ingredients:
        issues.append(_issue(
            "ingredients_missing", "error", "ingredients",
            "Нет списка ингредиентов",
        ))
        return issues

    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(ingredients):
        normalized = normalize_ingredient(raw)
        name = normalized.get("name") or ""
        field = f"ingredients[{index}]"
        if not name:
            issues.append(_issue(
                "ingredient_name_missing", "error", field,
                "Ингредиент без названия",
            ))
            continue

        raw_name = str(raw.get("name") if isinstance(raw, dict) else raw or "")
        if any(ch.isdigit() for ch in raw_name) or "(" in raw_name:
            issues.append(_issue(
                "ingredient_needs_parsing", "info", field,
                f"Количество/комментарий внутри имени: {raw_name!r}",
            ))

        amount = normalized.get("amount")
        unit = normalized.get("unit")
        optional = bool(normalized.get("optional"))
        if amount is None and not optional:
            issues.append(_issue(
                "missing_amount", "warning", field,
                f"{name}: не указано количество",
            ))
        if amount is not None and not unit:
            issues.append(_issue(
                "missing_unit", "warning", field,
                f"{name}: количество без единицы",
            ))
        if unit and unit not in CANONICAL_UNITS:
            issues.append(_issue(
                "non_canonical_unit", "warning", field,
                f"{name}: нестандартная единица {unit!r}",
            ))

        if not normalized.get("is_heading"):
            key = _ingredient_key(normalized)
            if key in seen:
                issues.append(_issue(
                    "duplicate_ingredient", "warning", field,
                    f"{name}: дубликат ингредиента",
                ))
            seen.add(key)

    return issues


def _lint_times(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    prep = recipe.get("prep_time")
    cook = recipe.get("cook_time")
    total = recipe.get("total_time")
    if prep is not None and not isinstance(prep, (int, float)):
        issues.append(_issue("bad_prep_time", "warning", "prep_time", "prep_time не число"))
    if cook is not None and not isinstance(cook, (int, float)):
        issues.append(_issue("bad_cook_time", "warning", "cook_time", "cook_time не число"))
    if isinstance(prep, (int, float)) and isinstance(cook, (int, float)):
        expected = int(prep) + int(cook)
        if total is None:
            issues.append(_issue(
                "total_time_missing", "info", "total_time",
                f"total_time не задан (ожидается {expected})",
            ))
        elif int(total) != expected:
            issues.append(_issue(
                "total_time_mismatch", "warning", "total_time",
                f"total_time={total}, а prep+cook={expected}",
            ))
    return issues


def lint_recipe(recipe: dict[str, Any], *, check_roundtrip: bool = True) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    if not (recipe.get("name") or "").strip():
        issues.append(_issue("name_missing", "error", "name", "Нет названия рецепта"))
    if not recipe.get("description"):
        issues.append(_issue("description_missing", "info", "description", "Нет описания"))
    if not recipe.get("instructions"):
        issues.append(_issue("instructions_missing", "error", "instructions", "Нет шагов"))
    if not recipe.get("servings"):
        issues.append(_issue("servings_missing", "warning", "servings", "Не указаны порции"))
    if recipe.get("servings") and not recipe.get("servings_text"):
        issues.append(_issue("servings_text_missing", "info", "servings_text", "Нет servings_text"))
    if not recipe.get("nutrition"):
        issues.append(_issue("nutrition_missing", "info", "nutrition", "Нет КБЖУ"))
    for key in ("courses", "categories", "collections"):
        if not normalize_list(recipe.get(key)):
            issues.append(_issue(f"{key}_empty", "info", key, f"Пустой список {key}"))
    if recipe.get("active_time_error"):
        issues.append(_issue(
            "active_time_error", "warning", "active_time_error",
            str(recipe.get("active_time_error"))[:200],
        ))
    if recipe.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue(
            "schema_version_missing", "info", "schema_version",
            f"Ожидается schema_version={SCHEMA_VERSION}",
        ))

    issues.extend(_lint_ingredients(recipe.get("ingredients")))
    issues.extend(_lint_times(recipe))

    if check_roundtrip:
        try:
            from services.md_export import recipe_to_md
            from recipe_manager.importer import parse_markdown_recipe
            md = recipe_to_md(recipe)
            parsed = parse_markdown_recipe(md)
            if len(parsed.get("ingredients") or []) != len(recipe.get("ingredients") or []):
                issues.append(_issue(
                    "md_roundtrip_ingredients", "warning", "ingredients",
                    "MD round-trip потерял ингредиенты",
                ))
            if len(parsed.get("instructions") or []) != len(recipe.get("instructions") or []):
                issues.append(_issue(
                    "md_roundtrip_instructions", "warning", "instructions",
                    "MD round-trip потерял шаги",
                ))
        except Exception as exc:  # noqa: BLE001
            issues.append(_issue(
                "md_roundtrip_failed", "warning", "md",
                f"MD round-trip не удался: {type(exc).__name__}: {exc}"[:300],
            ))

    issues.sort(key=lambda i: SEVERITY_ORDER.get(i.get("severity"), 9))
    return issues


def has_errors(issues: list[dict[str, Any]]) -> bool:
    return any(i.get("severity") == "error" for i in issues)


def summarize(issues: list[dict[str, Any]]) -> dict[str, int]:
    out = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        sev = issue.get("severity", "info")
        out[sev] = out.get(sev, 0) + 1
    return out
