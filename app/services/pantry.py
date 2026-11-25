"""Классификация продуктов: специи/запасы, которые обычно уже есть.

`pantry=True` — продукт не нужно каждый раз добавлять в список покупок.
Это эвристика; пользователь может переопределить флаг у продукта.
"""
from __future__ import annotations

from typing import Any

_PANTRY_EXACT = {
    "соль",
    "перец",
    "перец чёрный",
    "перец черный",
    "перец молотый",
    "перец чёрный молотый",
    "перец черный молотый",
    "перец красный",
    "перец горошком",
    "паприка",
    "орегано",
    "базилик",
    "сушёный базилик",
    "сушеный базилик",
    "розмарин",
    "тимьян",
    "кориандр",
    "мускатный орех",
    "лавровый лист",
    "специи",
    "приправа",
    "ванилин",
    "сода",
    "разрыхлитель",
    "сахар",
    "сахарный песок",
    "сахар-песок",
    "сахар песок",
    "сахарная пудра",
}
_PANTRY_CONTAINS = (
    "сушён", "сушен", "специ", "приправ", "лавров", "мускатн",
    "кориандр", "орегано", "паприк", "розмарин", "тимьян", "кориц",
)
_FRESH_MARKERS = ("свеж", "свежий", "свежая", "свежие")
_BELL_PEPPER_MARKERS = ("болгар", "сладк", "стручков")


def is_pantry_name(name: str | None) -> bool:
    text = (name or "").strip().lower().replace("ё", "е")
    if not text:
        return False
    if any(marker in text for marker in _FRESH_MARKERS):
        return False
    if any(marker in text for marker in _BELL_PEPPER_MARKERS):
        return False
    if text in {n.replace("ё", "е") for n in _PANTRY_EXACT}:
        return True
    if any(marker in text for marker in _PANTRY_CONTAINS):
        return True
    if "соль" in text:
        return True
    if "перец" in text and any(
        marker in text
        for marker in ("черн", "чёрн", "молот", "красн", "горош")
    ):
        return True
    return False


def is_pantry_ingredient(
    ingredient: dict[str, Any] | None,
    product: dict[str, Any] | None = None,
) -> bool:
    if isinstance(ingredient, dict) and isinstance(ingredient.get("pantry"), bool):
        return ingredient["pantry"]
    if isinstance(product, dict) and isinstance(product.get("pantry"), bool):
        return product["pantry"]
    return is_pantry_name((ingredient or {}).get("name"))


def annotate_ingredients(
    ingredients: list[Any],
    *,
    product_getter=None,
) -> list[Any]:
    """Проставляет pantry/essential в ингредиенты рецепта (in-place)."""
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            continue
        if ingredient.get("is_heading") or str(ingredient.get("name") or "").startswith("#"):
            continue
        product = None
        product_id = ingredient.get("product_id")
        if product_id and product_getter is not None:
            try:
                product = product_getter(str(product_id))
            except Exception:  # noqa: BLE001
                product = None
        pantry = is_pantry_ingredient(ingredient, product)
        ingredient["pantry"] = pantry
        ingredient["essential"] = not pantry
    return ingredients
