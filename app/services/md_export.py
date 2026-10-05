"""Экспорт рецепта в Markdown и импорт из Markdown-строки."""
from __future__ import annotations

from typing import Any

# Порядок полей во front matter — фиксированный для читаемости диффов
_FRONT_MATTER_ORDER = [
    "id",
    "title",
    "description",
    "tags",
    "courses",
    "categories",
    "collections",
    "cuisine",
    "category",
    "servings",
    "servings_text",
    "prep_time",
    "cook_time",
    "total_time",
    "source_url",
    "image_url",
    "rating",
    "is_favourite",
    "ingredients",
    "nutrition",
    "notes",
]


def _yaml_value(v: Any) -> str:
    """Простое представление значения для YAML без внешних библиотек.

    Строки — в кавычках, если содержат спецсимволы. Списки — inline.
    """
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        # Если список строк без спецсимволов — inline
        if all(isinstance(x, str) for x in v):
            return "[" + ", ".join(_yaml_string(x) for x in v) + "]"
        # Иначе — многострочно, но для front matter это усложнит парсинг
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        # Для nutrition
        items = ", ".join(f"{k}: {_yaml_value(val)}" for k, val in v.items() if val is not None)
        return "{" + items + "}"
    return _yaml_string(str(v))


def _yaml_string(s: str) -> str:
    """Строка → YAML-safe представление."""
    if not s:
        return '""'
    need_quotes = any(c in s for c in ":#{}[]&*!|>'\"%@`,")
    need_quotes = need_quotes or s.strip() != s
    need_quotes = need_quotes or s.lower() in ("true", "false", "null", "yes", "no")
    if need_quotes:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _ingredient_line(ing: Any) -> str:
    """Ингредиент → строка вида '500 г муки' или '{name, amount, unit, notes}'."""
    if isinstance(ing, str):
        return ing
    if not isinstance(ing, dict):
        return str(ing)
    if ing.get("is_heading") or (ing.get("name") or "").startswith("#"):
        return str(ing.get("name") or "")
    parts = []
    if ing.get("amount"):
        parts.append(str(ing["amount"]))
    if ing.get("unit"):
        parts.append(str(ing["unit"]))
    head = " ".join(parts)
    name = ing.get("name") or ""
    notes = f" ({ing['notes']})" if ing.get("notes") else ""
    return (head + " " + name + notes).strip()


def recipe_to_md(recipe: dict[str, Any]) -> str:
    """Преобразует dict рецепта в Markdown-строку с YAML front matter."""
    lines: list[str] = ["---"]

    for key in _FRONT_MATTER_ORDER:
        if key not in recipe:
            continue
        v = recipe[key]
        if v is None or v == [] or v == {}:
            continue
        if key == "ingredients":
            # Ингредиенты пишем структурированно через список объектов
            lines.append("ingredients:")
            for ing in v:
                if isinstance(ing, str):
                    lines.append(f"  - {_yaml_string(ing)}")
                elif isinstance(ing, dict):
                    if ing.get("is_heading") or (ing.get("name") or "").startswith("#"):
                        lines.append(f"  - name: {_yaml_string(str(ing.get('name') or ''))}")
                        lines.append("    is_heading: true")
                    else:
                        name = str(ing.get("name") or "")
                        lines.append(f"  - name: {_yaml_string(name)}")
                        if ing.get("amount"):
                            lines.append(f"    amount: {_yaml_value(ing['amount'])}")
                        if ing.get("unit"):
                            lines.append(f"    unit: {_yaml_string(str(ing['unit']))}")
                        if ing.get("notes"):
                            lines.append(f"    notes: {_yaml_string(str(ing['notes']))}")
            continue
        if key == "instructions":
            # Инструкции — в тело, не в front matter
            continue
        if key == "nutrition":
            if isinstance(v, dict):
                lines.append("nutrition:")
                for nk, nv in v.items():
                    if nv is None or nv == "":
                        continue
                    lines.append(f"  {nk}: {_yaml_value(nv)}")
            continue
        if key == "tags" or key == "courses" or key == "categories" or key == "collections":
            lines.append(f"{key}: {_yaml_value(v)}")
            continue
        if key == "notes":
            # Notes пишем в тело под заголовок ## Notes, но также сохраняем в front matter
            # чтобы парсер восстановил в правильное поле
            lines.append(f"notes: {_yaml_string(str(v))}")
            continue
        lines.append(f"{key}: {_yaml_value(v)}")

    lines.append("---")
    lines.append("")

    # Тело
    title = recipe.get("title") or recipe.get("name") or "Без названия"
    lines.append(f"# {title}")
    lines.append("")

    if recipe.get("description"):
        lines.append(str(recipe["description"]))
        lines.append("")

    ingredients = recipe.get("ingredients") or []
    if ingredients:
        lines.append("## Ингредиенты")
        lines.append("")
        for ing in ingredients:
            if isinstance(ing, dict) and (ing.get("is_heading") or (ing.get("name") or "").startswith("#")):
                heading = str(ing.get("name") or "").lstrip("#").strip()
                lines.append(f"### {heading}")
            else:
                lines.append(f"- {_ingredient_line(ing)}")
        lines.append("")

    instructions = recipe.get("instructions") or []
    if instructions:
        lines.append("## Шаги")
        lines.append("")
        for i, step in enumerate(instructions, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    if recipe.get("notes"):
        lines.append("## Заметки")
        lines.append("")
        lines.append(str(recipe["notes"]))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def recipe_filename(recipe: dict[str, Any]) -> str:
    """Генерирует безопасное имя файла для рецепта."""
    import re
    title = str(recipe.get("title") or recipe.get("name") or "recipe").strip()
    # Транслитерация кириллицы
    trans = {
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z",
        "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
        "с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch",
        "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
    }
    lowered = title.lower()
    slug_chars = []
    for ch in lowered:
        if ch in trans:
            slug_chars.append(trans[ch])
        elif ch.isalnum() and ord(ch) < 128:
            slug_chars.append(ch)
        elif ch in " -_":
            slug_chars.append("-")
    slug = "".join(slug_chars)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "recipe"
    slug = slug[:60]
    rid = recipe.get("id") or "no-id"
    return f"{slug}_{rid[:8]}.md"