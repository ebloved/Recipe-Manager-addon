"""Справочник групп аллергенов и исключаемых продуктов.

Важно: это не медицинский справочник. Сопоставление идёт по названиям
ингредиентов; сложные соусы, полуфабрикаты и следы могут не распознаваться.
"""
from __future__ import annotations

from typing import Any

# section: allergen | diet. Используется квизом и интерфейсом.
GROUPS: dict[str, dict[str, Any]] = {
    "gluten": {
        "label": "Глютен / пшеница",
        "section": "allergen",
        "aliases": [
            "пшениц", "пшеничн", "хлеб", "батон", "булк", "булоч",
            "макарон", "спагет", "лапш", "булгур", "кускус", "ячмен",
            "рожь", "ржан", "овёс", "овес", "овсян", "солод", "крекер",
            "печенье", "паста", "пенне", "фузилли", "тальятелле", "ригате",
            "лазань", "мука",
        ],
    },
    "milk": {
        "label": "Молоко и молочное",
        "section": "allergen",
        "aliases": [
            "молок", "молочн", "сливк", "сливочн", "сыр", "сырн", "творог",
            "творожн", "сметан", "кефир", "йогурт", "ряженк", "простокваш",
            "масло сливочное", "сливочное масло", "брынз", "моцарелл",
            "пармезан", "фета",
        ],
    },
    "egg": {
        "label": "Яйца",
        "section": "allergen",
        "aliases": ["яйц", "яичн", "яичный", "желток", "белок яичн", "майонез"],
    },
    "fish": {
        "label": "Рыба",
        "section": "allergen",
        "aliases": [
            "рыб", "лосос", "форел", "минтай", "треск", "тунец", "сельд",
            "скумбр", "сардин", "анчоус", "камбал", "судак", "карп", "щук",
            "рыбный соус",
        ],
    },
    "seafood": {
        "label": "Морепродукты",
        "section": "allergen",
        "aliases": [
            "кревет", "кальмар", "миди", "устриц", "краб", "лобстер",
            "рапан", "гребеш",
        ],
    },
    "nuts": {
        "label": "Орехи",
        "section": "allergen",
        "aliases": [
            "миндал", "грецк", "кешью", "фундук", "фисташ", "пекан",
            "макадам", "бразил", "орех", "орехов",
        ],
    },
    "peanut": {
        "label": "Арахис",
        "section": "allergen",
        "aliases": ["арахис"],
    },
    "soy": {
        "label": "Соя",
        "section": "allergen",
        "aliases": ["соя", "соев", "тофу", "эдамам", "мисо", "темпе"],
    },
    "sesame": {
        "label": "Кунжут",
        "section": "allergen",
        "aliases": ["кунжут", "тахин", "тахини"],
    },
    "mustard": {
        "label": "Горчица",
        "section": "allergen",
        "aliases": ["горчиц"],
    },
    "celery": {
        "label": "Сельдерей",
        "section": "allergen",
        "aliases": ["сельдер"],
    },
    "sulfites": {
        "label": "Сульфиты",
        "section": "allergen",
        "aliases": ["сульфит", "диоксид серы", "сернист"],
    },
    "meat": {
        "label": "Мясо",
        "section": "diet",
        "aliases": [
            "говяд", "свинин", "баранин", "телятин", "фарш", "колбас",
            "сосиск", "бекон", "ветчин", "сало", "печень",
        ],
    },
    "poultry": {
        "label": "Птица",
        "section": "diet",
        "aliases": [
            "курин", "куриц", "куриное", "куриный", "индейк", "индюшатин",
            "утк", "утин", "гус", "гусин", "перепел",
        ],
    },
}

# Исключения для слишком широкого «мука»/«паста»: безглютеновая мука
# не должна автоматически считаться глютеном.
_GLUTEN_SAFE_FLOURS = (
    "рисовая мука", "мука рисовая", "кукурузная мука", "мука кукурузная",
    "миндальная мука", "мука миндальная", "кокосовая мука", "мука кокосовая",
    "гречневая мука", "мука гречневая", "нутовая мука", "мука нутовая",
)
_GLUTEN_SAFE_PASTE = ("томатная паста", "паста томатная", "томатной пасте")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def recipe_text(recipe: dict[str, Any]) -> str:
    parts: list[str] = [_norm(recipe.get("name"))]
    for key in ("tags", "courses", "categories", "collections", "category"):
        value = recipe.get(key)
        items = value if isinstance(value, list) else [value]
        parts.extend(_norm(item) for item in items if _norm(item))
    for ing in recipe.get("ingredients") or []:
        if isinstance(ing, str):
            parts.append(_norm(ing))
        elif isinstance(ing, dict):
            parts.append(_norm(ing.get("name")))
    return " ".join(part for part in parts if part)


def match_groups(recipe: dict[str, Any], group_ids: list[str] | None) -> set[str]:
    """Возвращает группы, найденные в названии/ингредиентах рецепта."""
    if not group_ids:
        return set()
    text = recipe_text(recipe)
    matched: set[str] = set()
    for group_id in group_ids:
        group = GROUPS.get(str(group_id))
        if not group:
            continue
        aliases = group.get("aliases") or []
        hit = any(alias in text for alias in aliases)

        # Не считаем безглютеновую муку и томатную пасту глютеном.
        if group_id == "gluten" and hit:
            if (
                any(safe in text for safe in _GLUTEN_SAFE_FLOURS)
                and not any(
                    alias in text
                    for alias in ("пшениц", "хлеб", "батон", "булгур", "кускус", "ячмен", "рожь", "овсян")
                )
            ):
                hit = False
            if any(safe in text for safe in _GLUTEN_SAFE_PASTE) and not any(
                alias in text
                for alias in ("макарон", "спагет", "лапш", "пенне", "фузилли", "тальятелле")
            ):
                hit = False
        if hit:
            matched.add(group_id)
    return matched


def labels_for(group_ids: list[str] | None) -> list[str]:
    labels: list[str] = []
    for group_id in group_ids or []:
        group = GROUPS.get(str(group_id))
        if group:
            labels.append(str(group.get("label") or group_id))
    return labels
