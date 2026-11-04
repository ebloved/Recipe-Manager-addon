"""Канонический стандарт рецепта (по recipe_template.md).

Здесь только детерминированная нормализация структуры:
имена, количества, единицы, дубли, optional, производные поля.
LLM-обогащение — в recipe_enricher.py.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from services.shopping_normalizer import normalize_for_connector

SCHEMA_VERSION = 8

UNIT_ALIASES = {
    "г": "г", "гр": "г", "грамм": "г", "граммов": "г", "g": "г",
    "кг": "кг", "килограмм": "кг", "килограммов": "кг", "kg": "кг",
    "мл": "мл", "миллилитр": "мл", "миллилитров": "мл", "ml": "мл",
    "л": "л", "литр": "л", "литров": "л", "l": "л",
    "шт": "шт", "штук": "шт", "штука": "шт", "штуки": "шт",
    "пачка": "пачка", "пачки": "пачка", "пачек": "пачка",
    "уп": "пачка", "упаковка": "пачка", "упаковки": "пачка",
    "банка": "банка", "банки": "банка", "банок": "банка", "баночка": "банка",
    "зубчик": "зубчик", "зубчика": "зубчик", "зубчиков": "зубчик",
    "зубч": "зубчик", "зубч.": "зубчик",
    "пучок": "пучок", "пучка": "пучок", "пучков": "пучок",
    "веточка": "веточка", "веточки": "веточка", "веточек": "веточка",
    "щепотка": "щепотка", "щепотки": "щепотка", "щепоть": "щепотка",
    "ст. л.": "ст. л.", "ст.л.": "ст. л.", "ст л": "ст. л.", "стл": "ст. л.",
    "ст.": "ст. л.", "ст.ложка": "ст. л.",
    "ст ложка": "ст. л.", "ст ложки": "ст. л.",
    "столовая ложка": "ст. л.", "столовых ложек": "ст. л.",
    "ч. л.": "ч. л.", "ч.л.": "ч. л.", "ч л": "ч. л.", "чл": "ч. л.",
    "ч ложка": "ч. л.", "ч ложки": "ч. л.", "ч.ложка": "ч. л.",
    "чайная ложка": "ч. л.", "чайных ложек": "ч. л.",
    "стакан": "стакан", "стакана": "стакан", "стаканов": "стакан",
}

CANONICAL_UNITS = set(UNIT_ALIASES.values())

NAME_ALIASES = {
    "яйца": "яйцо",
    "яиц": "яйцо",
    "яйцо куриное": "яйцо",
    "яйца куриные": "яйцо",
    "творога": "творог",
    "творог мягкий": "творог мягкий",
    "муки": "мука пшеничная",
    "мука": "мука пшеничная",
    "сахара": "сахар",
    "соли": "соль",
    "молока": "молоко",
    "лука": "лук репчатый",
    "лук": "лук репчатый",
    "хлеба": "хлеб",
    "белый хлеб": "хлеб белый",
    "белый хлеб без корки": "хлеб белый",
    "хлеб без корки": "хлеб белый",
    "батон": "батон нарезной",
    "батон нарезной": "батон нарезной",
    "тостовый хлеб": "хлеб тостовый",
    "хлеб тостовый": "хлеб тостовый",
    "масла": "масло",
    "воды": "вода",
    "мяса": "мясо",
    "перца": "перец",
    "крахмала": "крахмал",
    "разрыхлителя": "разрыхлитель",
    "ванилина": "ванилин",
}

CONDIMENTS = {
    "соль", "перец", "перец чёрный молотый", "перец черный молотый",
    "сахар", "ванилин", "зелень", "специи", "приправа", "лавровый лист",
}

CONDIMENT_KEYWORDS = (
    "соль", "перец", "сахар", "ванилин", "специ", "приправ", "лавровый",
    "зелень", "укроп", "петрушк", "тимьян", "базилик", "мускатн", "кориандр",
)

NON_QUANTIFIED_KEYWORDS = (
    "для промывки", "для замачивания", "для подачи", "для украшения",
    "для обваливания", "по необходимости",
)

OPTIONAL_MARKERS = (
    "по вкусу", "по желанию", "опционально", "для подачи", "для украшения",
)


def _is_condiment(name: str) -> bool:
    text = (name or "").lower()
    return any(keyword in text for keyword in CONDIMENT_KEYWORDS)


def _is_non_quantified(name: str) -> bool:
    text = (name or "").lower()
    return any(keyword in text for keyword in NON_QUANTIFIED_KEYWORDS)

_PACKAGE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>шт|штук|пачк\w*|уп\w*)\s+по\s+"
    r"(?P<per>\d+(?:[.,]\d+)?)\s*(?P<per_unit>г|гр|кг|мл|л)$",
    re.IGNORECASE,
)
_SPOON_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>ст\.?\s*л\.?|ч\.?\s*л\.?|ст\.?\s*ложк\w*|"
    r"ч\.?\s*ложк\w*|стакан\w*)$",
    re.IGNORECASE,
)
_TRAILING_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>г|гр|кг|мл|л|шт|штук|пачк\w*|банк\w*|"
    r"зубчик\w*|пучок|пучка|веточк\w*)$",
    re.IGNORECASE,
)
_LEADING_RE = re.compile(
    r"^(?P<amount>\d+(?:[.,]\d+)?)\s+(?P<name>.+)$"
)
_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")


def _num(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def normalize_unit(unit: Any) -> str | None:
    if unit is None:
        return None
    text = re.sub(r"\s+", " ", str(unit).strip().lower())
    return UNIT_ALIASES.get(text, text or None)


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


def _optional_from_text(*parts: str | None) -> bool:
    text = " ".join(p for p in parts if p).lower()
    return any(marker in text for marker in OPTIONAL_MARKERS)


def canonical_name(name: str) -> str:
    text = re.sub(r"\s+", " ", (name or "").strip())
    text = text.strip(" .,:;")
    key = text.lower()
    text = NAME_ALIASES.get(key, text)
    if text:
        text = text[0].upper() + text[1:]
    return text


def normalize_ingredient(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        data: dict[str, Any] = {"name": raw}
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        return {"name": "", "amount": None, "unit": None, "notes": None}

    if data.get("is_heading") or str(data.get("name") or "").startswith("#"):
        return {"name": str(data.get("name") or "").lstrip("#").strip(), "is_heading": True}

    name = str(data.get("name") or "").strip()
    amount = _num(data.get("amount"))
    unit = normalize_unit(data.get("unit"))
    notes = data.get("notes")

    # Разделитель "Название - 1 ст. ложка" → пробел, чтобы сработали regex.
    name = re.sub(r"\s+[-–—]\s+", " ", name).strip(" -–—")

    # Скобки в имени → notes
    paren = _PAREN_RE.search(name)
    if paren:
        notes = _merge_note(notes, paren.group(1))
        name = _PAREN_RE.sub("", name).strip()

    # "Мягкий творог 2шт по 125гр"
    if amount is None and not unit:
        m = _PACKAGE_RE.match(name)
        if m:
            name = m.group("name").strip()
            amount = _num(m.group("amount"))
            unit = "пачка"
            notes = _merge_note(notes, f"по {m.group('per')} {m.group('per_unit')}")

    # "Крахмал 1ст ложка"
    if amount is None and not unit:
        m = _SPOON_RE.match(name)
        if m:
            name = m.group("name").strip()
            amount = _num(m.group("amount"))
            unit = normalize_unit(m.group("unit"))

    # "мука 120 г"
    if amount is None and not unit:
        m = _TRAILING_RE.match(name)
        if m:
            name = m.group("name").strip()
            amount = _num(m.group("amount"))
            unit = normalize_unit(m.group("unit"))

    # "3 яйца"
    if amount is None and not unit:
        m = _LEADING_RE.match(name)
        if m:
            amount = _num(m.group("amount"))
            name = m.group("name").strip()
            unit = "шт"

    # "по вкусу" внутри имени
    if _optional_from_text(name, notes):
        name = re.sub(
            r"\b(по вкусу|по желанию|опционально|для подачи|для украшения)\b",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip(" .,:;")
    name = canonical_name(name)
    if not name:
        return {"name": "", "amount": None, "unit": None, "notes": notes}

    optional = bool(data.get("optional"))
    if amount is None and (unit is None or _is_condiment(name)):
        if _is_condiment(name) or name.lower() in CONDIMENTS:
            optional = True
            notes = _merge_note(notes, "по вкусу")
        elif _is_non_quantified(name):
            optional = True
            notes = _merge_note(notes, "по необходимости")
        elif _optional_from_text(name, notes):
            optional = True
            notes = _merge_note(notes, "по желанию")

    result = {
        "name": name,
        "amount": amount,
        "unit": unit,
        "notes": notes or None,
        **({"optional": True} if optional else {}),
    }
    for key in ("product_id", "barcode", "brand"):
        if data.get(key):
            result[key] = data[key]
    return result


def _ingredient_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        normalize_for_connector(item.get("name") or ""),
        (item.get("unit") or "").lower(),
    )


def dedupe_ingredients(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index: dict[tuple[str, str], int] = {}
    for item in items:
        if item.get("is_heading"):
            result.append(item)
            continue
        key = _ingredient_key(item)
        if key not in index:
            index[key] = len(result)
            result.append(item)
            continue

        current = result[index[key]]
        old_amount = _num(current.get("amount"))
        new_amount = _num(item.get("amount"))
        if old_amount is not None and new_amount is not None:
            current["amount"] = old_amount + new_amount
        elif new_amount is not None:
            current["amount"] = new_amount
        current["notes"] = _merge_note(current.get("notes"), item.get("notes"))
        current["optional"] = bool(current.get("optional") and item.get("optional"))
        if current.get("amount") is not None:
            current.pop("optional", None)
        for key in ("product_id", "barcode", "brand"):
            if not current.get(key) and item.get(key):
                current[key] = item[key]
    return result


def normalize_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw = re.split(r"[,;]", values)
    elif isinstance(values, list):
        raw = values
    else:
        raw = [values]
    seen: set[str] = set()
    out: list[str] = []
    for value in raw:
        text = str(value).strip().lower()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def servings_text(servings: int | None) -> str | None:
    if not servings:
        return None
    if servings % 10 == 1 and servings % 100 != 11:
        word = "порция"
    elif servings % 10 in (2, 3, 4) and servings % 100 not in (12, 13, 14):
        word = "порции"
    else:
        word = "порций"
    return f"{servings} {word}"


def source_hash(recipe: dict[str, Any]) -> str:
    payload = {
        "name": recipe.get("name"),
        "description": recipe.get("description"),
        "ingredients": recipe.get("ingredients"),
        "instructions": recipe.get("instructions"),
        "prep_time": recipe.get("prep_time"),
        "cook_time": recipe.get("cook_time"),
        "total_time": recipe.get("total_time"),
        "servings": recipe.get("servings"),
        "tags": recipe.get("tags"),
        "courses": recipe.get("courses"),
        "categories": recipe.get("categories"),
        "collections": recipe.get("collections"),
        "nutrition": recipe.get("nutrition"),
        "notes": recipe.get("notes"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
