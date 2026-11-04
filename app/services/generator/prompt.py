"""Сборка промпта для LLM."""
from __future__ import annotations

from typing import Any


SYSTEM_PROMPT = (
    "Ты — опытный повар, генерирующий рецепты для домашней кухни. "
    "Соблюдай ограничения профиля (если заданы). "
    "Формат ответа: Markdown с YAML front matter, соответствующий примерам ниже. "
    "СТРОГОЕ ПРАВИЛО: Твой ответ должен начинаться СРАЗУ с --- (YAML front matter). "
    "Никакого текста, заголовков или пояснений до первого ---. "
    "В ингредиентах используй ключ name: (а не item:). "
    "Не выдумывай названия брендов и продуктов, которых нет в реальности. "
    "Используй ингредиенты, реально доступные в обычном магазине. "
    "Пиши на русском языке."
)


def _fmt_list(items: Any) -> str:
    if not items:
        return "нет"
    if isinstance(items, list):
        return ", ".join(str(x) for x in items if str(x).strip()) or "нет"
    return str(items)


def _fmt_num(v: Any, unit: str) -> str:
    if v is None or v == "":
        return "не задано"
    try:
        return f"{v} {unit}"
    except Exception:  # noqa: BLE001
        return "не задано"


def _recipe_to_md(recipe: dict[str, Any]) -> str:
    """Мини-сериализатор рецепта в Markdown для few-shot примера."""
    fm: list[str] = ["---"]

    def push(k: str, v: Any) -> None:
        if v is None or v == "" or (isinstance(v, list) and not v):
            return
        if isinstance(v, list):
            fm.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        elif isinstance(v, str) and any(c in v for c in ':#,'):
            fm.append(f"{k}: {v!r}".replace("'", '"'))
        else:
            fm.append(f"{k}: {v}")

    push("title", recipe.get("name") or recipe.get("title"))
    push("description", recipe.get("description"))
    push("tags", recipe.get("tags"))
    push("courses", recipe.get("courses"))
    push("servings", recipe.get("servings"))
    push("prep_time", recipe.get("prep_time"))
    push("cook_time", recipe.get("cook_time"))

    nutrition = recipe.get("nutrition")
    if isinstance(nutrition, dict) and nutrition:
        fm.append("nutrition:")
        for k, v in nutrition.items():
            if v not in (None, ""):
                fm.append(f"  {k}: {v}")

    ingredients = recipe.get("ingredients") or []
    if ingredients:
        fm.append("ingredients:")
        for ing in ingredients:
            if isinstance(ing, str):
                fm.append(f"  - name: {ing}")
                continue
            name = ing.get("name") or ""
            if not name:
                continue
            fm.append(f"  - name: {name}")
            if ing.get("amount"):
                fm.append(f"    amount: {ing['amount']}")
            if ing.get("unit"):
                fm.append(f"    unit: {ing['unit']}")
            if ing.get("notes"):
                fm.append(f"    notes: {ing['notes']}")

    fm.append("---")
    fm.append("")
    fm.append(f"# {recipe.get('name') or 'Рецепт'}")
    fm.append("")

    if ingredients:
        fm.append("## Ингредиенты")
        for ing in ingredients:
            if isinstance(ing, str):
                fm.append(f"- {ing}")
                continue
            parts = []
            if ing.get("amount"):
                parts.append(str(ing["amount"]))
            if ing.get("unit"):
                parts.append(str(ing["unit"]))
            head = " ".join(parts)
            fm.append(f"- {head + ' ' if head else ''}{ing.get('name') or ''}")

    instructions = recipe.get("instructions") or []
    if instructions:
        fm.append("")
        fm.append("## Шаги")
        for i, step in enumerate(instructions, 1):
            fm.append(f"{i}. {step}")

    return "\n".join(fm)


def build_prompt(
    profile: dict[str, Any] | None,
    samples: list[dict[str, Any]],
    topic: str | None,
    count: int,
) -> tuple[str, str]:
    """Возвращает (system, user) для вызова .complete()."""
    c = (profile or {}).get("constraints") or {}

    lines: list[str] = []
    if profile:
        lines.append(f"Профиль: {profile.get('name', '—')} — {profile.get('description') or ''}".rstrip(" —"))
        lines.append("")
        lines.append("Ограничения профиля:")
        lines.append(f"- Максимум калорий на порцию: {_fmt_num(c.get('max_calories_per_serving'), 'ккал')}")
        lines.append(f"- Максимум активного времени: {_fmt_num(c.get('max_active_time_min'), 'мин')}")
        lines.append(f"- Максимум общего времени: {_fmt_num(c.get('max_total_time_min'), 'мин')}")
        lines.append(f"- Избегать способов готовки: {_fmt_list(c.get('avoid_methods'))}")
        lines.append(f"- Предпочитать способы готовки: {_fmt_list(c.get('prefer_methods'))}")
        lines.append(f"- Избегать ингредиентов: {_fmt_list(c.get('avoid_ingredients'))}")
        lines.append(f"- Предпочитать ингредиенты: {_fmt_list(c.get('prefer_ingredients'))}")
        lines.append(f"- Минимум белка на порцию: {_fmt_num(c.get('min_protein_per_serving_g'), 'г')}")
    else:
        lines.append("Профиль не задан — генерируй свободно, без ограничений.")

    lines.append("")
    lines.append(f"Тема: {topic.strip() if topic else 'любая, на твой выбор'}")
    lines.append("")
    lines.append(f"Сгенерируй {count} новых рецепт(ов).")

    if samples:
        lines.append("")
        lines.append("Примеры стиля (НЕ копируй их, используй только как образец структуры):")
        for sample in samples:
            lines.append("---")
            lines.append(_recipe_to_md(sample))

    lines.append("")
    lines.append("Верни только Markdown-рецепты.")
    if count > 1:
        lines.append("Между рецептами (если count > 1) разделитель: строка `---SPLIT---`.")
    lines.append("Без ``` вокруг. Без пояснений до или после.")
    lines.append("Начинай ответ с ---. Используй name: для ингредиентов.")

    return SYSTEM_PROMPT, "\n".join(lines)
