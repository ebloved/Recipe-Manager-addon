"""Экспорт рецепта в Markdown и импорт из Markdown-строки.

Ключевое дополнение относительно предыдущей версии:
  - В front matter каждого ингредиента может присутствовать
    опциональный блок `product` с полями `uuid` и `barcode`.
    Это обеспечивает переносимость связок между инсталляциями:

      ingredients:
        - name: Греческий йогурт 2%
          amount: 200
          unit: г
          product:
            uuid: 3f8a12bc-...
            barcode: 4607123456789

  - `barcode` — универсальный идентификатор, работает между установками.
  - `uuid` — локальный идентификатор, используется как fallback, если
    barcode нет (продукт создан вручную, без OFF).

Экспорт всегда пишет оба поля, если они есть. Импорт (см.
recipe_manager/importer.py) читает их по приоритету:
  barcode → uuid → имя.
"""
from __future__ import annotations

import re
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


# ---------------------------------------------------------------------------
# YAML-сериализация (минимальная, без внешних зависимостей)
# ---------------------------------------------------------------------------

def _yaml_value(v: Any) -> str:
    """Простое представление значения для YAML.

    Строки — в кавычках, если содержат спецсимволы. Списки — inline.
    Словари — inline (для коротких), многострочно — для вложенных.
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
        if all(isinstance(x, str) for x in v):
            return "[" + ", ".join(_yaml_string(x) for x in v) + "]"
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        items = ", ".join(
            f"{k}: {_yaml_value(val)}" for k, val in v.items() if val is not None
        )
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


# ---------------------------------------------------------------------------
# Экспорт ингредиента
# ---------------------------------------------------------------------------

def _ingredient_line(ing: Any) -> str:
    """Ингредиент → строка вида '500 г муки' (для тела MD, не для front matter)."""
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


def _ingredient_front_matter(ing: Any, out: list[str]) -> None:
    """Пишет ингредиент в front matter как YAML-объект.

    Поддерживает опциональный блок product с uuid и/или barcode.
    """
    if isinstance(ing, str):
        out.append(f"  - name: {_yaml_string(ing)}")
        return

    if not isinstance(ing, dict):
        out.append(f"  - name: {_yaml_string(str(ing))}")
        return

    # Подзаголовок (секция типа "Для бульона")
    if ing.get("is_heading") or (ing.get("name") or "").startswith("#"):
        out.append(f"  - name: {_yaml_string(str(ing.get('name') or ''))}")
        out.append("    is_heading: true")
        return

    # Обычный ингредиент
    name = str(ing.get("name") or "")
    out.append(f"  - name: {_yaml_string(name)}")

    if ing.get("amount"):
        out.append(f"    amount: {_yaml_value(ing['amount'])}")
    if ing.get("unit"):
        out.append(f"    unit: {_yaml_string(str(ing['unit']))}")
    if ing.get("notes"):
        out.append(f"    notes: {_yaml_string(str(ing['notes']))}")

    # --- Блок product (uuid + barcode) ---
    #
    # Источники данных:
    #   1. ing["product_id"] — внутренний UUID продукта в этой базе.
    #   2. ing["product"]     — развёрнутый dict (если ингредиент уже обогащён).
    #
    # При экспорте отдаём оба поля, если они доступны. Для получения
    # barcode обращаемся к ingredients_store (см. вызов в recipe_to_md).

    product_uuid: str | None = None
    product_barcode: str | None = None

    # Случай 1: ингредиент хранит product_id напрямую
    if isinstance(ing.get("product_id"), str) and ing["product_id"]:
        product_uuid = ing["product_id"]

    # Случай 2: ингредиент хранит вложенный объект product с готовыми данными
    nested = ing.get("product")
    if isinstance(nested, dict):
        if nested.get("uuid"):
            product_uuid = product_uuid or str(nested["uuid"])
        if nested.get("barcode"):
            product_barcode = str(nested["barcode"])

    # Случай 3: явный barcode в самом ингредиенте
    if ing.get("barcode"):
        product_barcode = product_barcode or str(ing["barcode"])

    if product_uuid or product_barcode:
        out.append("    product:")
        if product_uuid:
            out.append(f"      uuid: {_yaml_string(product_uuid)}")
        if product_barcode:
            out.append(f"      barcode: {_yaml_string(product_barcode)}")


# ---------------------------------------------------------------------------
# Экспорт рецепта
# ---------------------------------------------------------------------------

def recipe_to_md(recipe: dict[str, Any]) -> str:
    """Преобразует dict рецепта в Markdown-строку с YAML front matter.

    Для ингредиентов с product_id делает lookup в ingredients_store,
    чтобы вытащить barcode. Если store недоступен — пишет только uuid.
    Это позволяет экспортировать даже в окружении, где база продуктов
    ещё не загружена.
    """
    # Ленивая попытка получить store, чтобы обогатить ингредиенты barcode-ами.
    try:
        from stores import ingredients_store  # type: ignore[import]
    except Exception:  # noqa: BLE001
        ingredients_store = None  # type: ignore[assignment]

    # Обогащаем копии ингредиентов: добавляем product с barcode, если найдём.
    enriched_ingredients: list[Any] = []
    for ing in recipe.get("ingredients") or []:
        if not isinstance(ing, dict):
            enriched_ingredients.append(ing)
            continue

        enriched = dict(ing)
        product_id = ing.get("product_id")
        if product_id and ingredients_store is not None:
            product = ingredients_store.get_active(product_id)
            if product:
                enriched["product"] = {
                    "uuid": product.get("product_id"),
                    "barcode": product.get("barcode"),
                }
        enriched_ingredients.append(enriched)

    lines: list[str] = ["---"]

    for key in _FRONT_MATTER_ORDER:
        if key not in recipe:
            continue
        v = recipe[key]
        if v is None or v == [] or v == {}:
            continue

        if key == "ingredients":
            lines.append("ingredients:")
            for ing in enriched_ingredients:
                _ingredient_front_matter(ing, lines)
            continue

        if key == "instructions":
            # инструкции идут в тело, не в front matter
            continue

        if key == "nutrition":
            if isinstance(v, dict):
                lines.append("nutrition:")
                for nk, nv in v.items():
                    if nv is None or nv == "":
                        continue
                    lines.append(f"  {nk}: {_yaml_value(nv)}")
            continue

        if key in ("tags", "courses", "categories", "collections"):
            lines.append(f"{key}: {_yaml_value(v)}")
            continue

        if key == "notes":
            lines.append(f"notes: {_yaml_string(str(v))}")
            continue

        lines.append(f"{key}: {_yaml_value(v)}")

    lines.append("---")
    lines.append("")

    # --- Тело ---
    title = recipe.get("title") or recipe.get("name") or "Без названия"
    lines.append(f"# {title}")
    lines.append("")

    if recipe.get("description"):
        lines.append(str(recipe["description"]))
        lines.append("")

    if enriched_ingredients:
        lines.append("## Ингредиенты")
        lines.append("")
        for ing in enriched_ingredients:
            if isinstance(ing, dict) and (
                ing.get("is_heading") or (ing.get("name") or "").startswith("#")
            ):
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


# ---------------------------------------------------------------------------
# Имя файла
# ---------------------------------------------------------------------------

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def recipe_filename(recipe: dict[str, Any]) -> str:
    """Генерирует безопасное имя файла для рецепта.

    Формат: <transliterated-slug>_<8-символов-id>.md
    Суффикс из id нужен, чтобы два рецепта с одинаковым названием не
    перезаписывали друг друга при экспорте в одну папку.
    """
    title = str(recipe.get("title") or recipe.get("name") or "recipe").strip()
    lowered = title.lower()

    slug_chars: list[str] = []
    for ch in lowered:
        if ch in _TRANSLIT:
            slug_chars.append(_TRANSLIT[ch])
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
    short_id = str(rid).replace("-", "")[:8]

    return f"{slug}_{short_id}.md"