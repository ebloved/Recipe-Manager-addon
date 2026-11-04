"""Обогащение рецепта: быстрая связка ингредиентов с продуктами RM.

Использует только локальный fuzzy-матчер (без сети/LLM). Спорные случаи
уходят в issues для ручного подтверждения.
"""
from __future__ import annotations

import copy
from typing import Any

from config import MATCHER_AUTO_THRESHOLD, MATCHER_SUGGEST_THRESHOLD
from services.matcher.local_fuzzy import local_fuzzy_matcher
from stores import ingredients_store


def _issue(code: str, field: str, message: str, severity: str = "warning") -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


async def enrich_recipe(recipe: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Связывает ингредиенты с products из ingredients_store.

    Применяет только кандидатов с score >= MATCHER_AUTO_THRESHOLD.
    suggest/not_found уходят в issues.
    """
    out = copy.deepcopy(recipe)
    ingredients = out.get("ingredients") or []
    issues: list[dict[str, Any]] = []
    raw_products = getattr(ingredients_store, "products", None) or {}
    products = list(raw_products.values()) if isinstance(raw_products, dict) else list(raw_products)

    for index, ing in enumerate(ingredients):
        if not isinstance(ing, dict) or ing.get("is_heading"):
            continue
        if ing.get("product_id"):
            continue
        name = str(ing.get("name") or "").strip()
        if not name:
            continue

        try:
            candidates = local_fuzzy_matcher.find(name, products, limit=5)
        except Exception as exc:  # noqa: BLE001
            issues.append(_issue(
                "product_match_failed", f"ingredients[{index}]",
                f"{name}: матчер не сработал: {type(exc).__name__}: {exc}",
            ))
            continue

        best = candidates[0] if candidates else None
        if (
            best is not None
            and best.product_id
            and best.score >= MATCHER_AUTO_THRESHOLD
        ):
            ing["product_id"] = best.product_id
            if best.barcode:
                ing["barcode"] = best.barcode
            if best.brand and not ing.get("brand"):
                ing["brand"] = best.brand
            continue

        if best is not None and best.score >= MATCHER_SUGGEST_THRESHOLD:
            issues.append(_issue(
                "product_needs_review", f"ingredients[{index}]",
                f"{name}: кандидат {best.name!r} (score={best.score:.2f})",
                severity="info",
            ))
        else:
            issues.append(_issue(
                "product_not_found", f"ingredients[{index}]",
                f"{name}: продукт не найден в базе RM",
                severity="info",
            ))

    return out, issues
