"""Ремонт названий ингредиентов, повреждённых старым парсером.

Примеры:
  «Л. Л. Растительное масло» -> «Растительное масло»
  «Л. Сода» -> «Сода»
  «Г Спагетти» -> «Спагетти», unit=«г»
  «Соль (» + «Минимально)» -> «Соль», notes=«по вкусу; минимально»
"""
from __future__ import annotations

import re
from typing import Any

from services.pantry import is_pantry_ingredient, is_pantry_name
from services.recipe_standard import normalize_unit

_UNIT_PREFIX_RE = re.compile(
    r"^(г|мл|шт|зубчик|пучок|стакан)\s+",
    re.IGNORECASE,
)
_SPOON_PREFIX_RE = re.compile(
    r"^(ст\.?\s*л\.?|ч\.?\s*л\.?|ложка|ложки|ложек)\s+",
    re.IGNORECASE,
)
_L_PREFIX_RE = re.compile(r"^л\.?\s+", re.IGNORECASE)

_FRAGMENT_STARTS = (
    "осторожно", "минимально", "по вкусу", "щепотка",
    "или ", "можно ", "не ", "добав", "для ", "чтобы ", "если ",
)
_SUGAR_NAMES = {
    "сахар", "сахарный песок", "сахар-песок", "сахар песок", "сахарная пудра",
}


def _merge_note(old: str | None, new: str | None) -> str | None:
    old = (old or "").strip()
    new = (new or "").strip()
    if not new:
        return old or None
    if not old:
        return new
    if new in old:
        return old
    return f"{old}; {new}"


def _clean_notes(notes: Any) -> str | None:
    if notes is None:
        return None
    text = str(notes).strip()
    if not text:
        return None
    if (
        text.startswith("(")
        and text.endswith(")")
        and text.count("(") == 1
        and text.count(")") == 1
    ):
        text = text[1:-1].strip()
    missing = text.count("(") - text.count(")")
    if missing > 0:
        text += ")" * missing
    return text or None


def _strip_name(name: Any) -> tuple[str, str | None, str | None]:
    text = re.sub(r"\s+", " ", str(name or "").strip())
    extra_note = None
    unit = None

    while True:
        match = _L_PREFIX_RE.match(text)
        if match:
            text = text[match.end():]
            continue
        match = _SPOON_PREFIX_RE.match(text)
        if match:
            token = match.group(1).lower()
            if token.startswith("ст"):
                unit = unit or "ст. л."
            elif token.startswith("ч"):
                unit = unit or "ч. л."
            text = text[match.end():]
            continue
        match = _UNIT_PREFIX_RE.match(text)
        if match:
            unit = unit or match.group(1).lower()
            text = text[match.end():]
            continue
        break

    text = text.strip(" .,:;")
    if text.endswith("("):
        text = text[:-1].strip()
    if text.endswith(")") and "(" not in text:
        inner = text[:-1].strip()
        if "," in inner:
            base, extra = inner.split(",", 1)
            text = base.strip()
            extra_note = extra.strip() or None
        else:
            text = inner
    text = re.sub(r"\s+", " ", text).strip(" .,:;")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text, extra_note, unit


def _is_fragment(name: str, amount: Any, unit: Any) -> bool:
    if amount not in (None, "") or unit not in (None, ""):
        return False
    text = (name or "").strip().lower()
    if not text:
        return False
    return text.startswith(_FRAGMENT_STARTS)


def _is_sugar(name: str) -> bool:
    text = re.sub(r"\s+", " ", (name or "").strip().lower().replace("ё", "е"))
    return text in {n.replace("ё", "е") for n in _SUGAR_NAMES}


def clean_ingredients(
    ingredients: list[Any],
    *,
    product_getter=None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    result: list[Any] = []
    changes: list[dict[str, Any]] = []

    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            result.append(ingredient)
            continue
        if ingredient.get("is_heading") or str(ingredient.get("name") or "").startswith("#"):
            result.append(ingredient)
            continue

        original = dict(ingredient)
        name, extra_note, prefix_unit = _strip_name(ingredient.get("name"))
        notes = _clean_notes(ingredient.get("notes"))
        if extra_note:
            notes = _merge_note(notes, extra_note)
        amount = ingredient.get("amount")
        unit = ingredient.get("unit")
        if not unit and prefix_unit:
            unit = prefix_unit
        if unit:
            unit = normalize_unit(unit)

        if _is_fragment(name, amount, unit):
            previous = result[-1] if result else None
            if isinstance(previous, dict) and not previous.get("is_heading"):
                previous["notes"] = _merge_note(previous.get("notes"), name)
                changes.append({
                    "type": "merged_fragment",
                    "recipe_ingredient": original.get("name"),
                    "into": previous.get("name"),
                    "fragment": name,
                })
                continue

        updated = dict(ingredient)
        updated["name"] = name
        updated["notes"] = notes or None
        updated["unit"] = unit

        name_changed = (
            name != str(original.get("name") or "").strip()
            or unit != original.get("unit")
            or notes != original.get("notes")
        )
        product = None
        product_id = ingredient.get("product_id")
        if product_id and product_getter is not None:
            try:
                product = product_getter(str(product_id))
            except Exception:  # noqa: BLE001
                product = None
        pantry = is_pantry_ingredient({"name": name}, product)
        if is_pantry_name(name):
            pantry = True
        if _is_sugar(name):
            pantry = True
        updated["pantry"] = pantry
        updated["essential"] = not pantry

        if updated != original:
            changes.append({
                "type": "updated",
                "recipe_ingredient": original.get("name"),
                "name": name,
                "unit_before": original.get("unit"),
                "unit_after": unit,
                "notes_before": original.get("notes"),
                "notes_after": notes,
                "pantry": updated.get("pantry"),
            })
        result.append(updated)

    return result, changes
