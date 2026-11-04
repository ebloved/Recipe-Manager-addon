"""Разбор надиктованного текста в структуру рецепта.

Сначала пробуем локальные эвристики. Если текста не хватает — просим LLM
только структурировать сказанное, без выдумывания новых продуктов.
"""
from __future__ import annotations

import json
import re
from typing import Any

from recipe_manager.importer import _parse_ingredient_line

_SECTION_ING = re.compile(
    r"(?i)\b(ингредиенты|состав|продукты)\b\s*[:\-—.]?"
)
_SECTION_STEPS = re.compile(
    r"(?i)\b(шаги|приготовление|инструкции|как готовить|"
    r"способ приготовления|процесс)\b\s*[:\-—.]?"
)

_UNIT = (
    r"(?:г|гр|грамм(?:ов|а)?|кг|килограмм(?:ов|а)?|мг|мл|л|литр(?:ов|а)?|"
    r"шт|штук(?:а|и)?|ст\.?\s*л\.?|столов(?:ая|ые|ых)?\s*ложк(?:а|и)?|"
    r"ч\.?\s*л\.?|чай(?:ная|ные|ных)?\s*ложк(?:а|и)?|"
    r"зубчик(?:ов|а)?|стакан(?:а|ов)?|щепотк(?:а|и)?|"
    r"пучок|пучка|пучков|веточк(?:а|и)?|головк(?:а|и)?|"
    r"ломтик(?:а|ов)?|кусок|куска|кусков|банк(?:а|и)?|"
    r"упаковк(?:а|и)?|пачк(?:а|и)?|пакет(?:а|ов)?)"
)

_SYSTEM = (
    "Ты — аккуратный парсер рецептов. Твоя задача — только структурировать "
    "уже сказанный текст. Не добавляй ингредиенты, шаги, количества или "
    "факты, которых нет в тексте. Если чего-то нет — оставь null или пустой "
    "список. Отвечай строго валидным JSON без markdown и комментариев."
)

_PROMPT = """Преврати надиктованный текст в рецепт.

Верни строго JSON такой формы:
{{
  "name": "название",
  "description": "краткое описание или null",
  "ingredients": [
    {{"name": "продукт", "amount": 500, "unit": "г", "notes": null}}
  ],
  "instructions": ["шаг 1", "шаг 2"],
  "tags": [],
  "servings": null,
  "prep_time": null,
  "cook_time": null,
  "total_time": null
}}

Правила:
- не выдумывай продукты и шаги;
- если количество не названо — amount: null, unit: null;
- если единица не названа — unit: null;
- шаги сохраняй в том порядке, в котором они были сказаны;
- если название не названо — сделай короткое название по составу.

Текст:
{text}
"""


def _clean_title(value: str) -> str:
    title = re.sub(
        r"(?i)^\s*(название|рецепт|блюдо|называется)\s*[:\-—.]?\s*",
        "",
        value.strip(),
    )
    title = title.strip(" .;:—-\n\t")
    if len(title) > 150:
        title = title[:150].rsplit(" ", 1)[0].strip()
    return title


def _split_ingredient_phrases(block: str) -> list[str]:
    block = re.sub(r"(?i)^\s*[:\-—.]\s*", "", block.strip())
    parts = re.split(r"[,;\n]+|\s+и\s+", block)
    return [
        re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", part).strip(" .;:—-\n\t")
        for part in parts
        if part.strip(" .;:—-\n\t")
    ]


def _parse_ingredient_phrase(phrase: str) -> dict[str, Any] | None:
    phrase = phrase.strip(" .;:—-\n\t")
    if not phrase:
        return None

    notes_match = re.match(
        r"(?i)^(.+?)\s+(по вкусу|для подачи|по желанию|для украшения)$",
        phrase,
    )
    if notes_match:
        return {
            "name": notes_match.group(1).strip(),
            "amount": None,
            "unit": None,
            "notes": notes_match.group(2),
        }

    # «творог 500 грамм» → «творог — 500 грамм»
    suffix = re.match(
        rf"(?i)^(.+?)\s+(\d+(?:[.,/]\d+)?"
        rf"(?:\s*[-–]\s*\d+(?:[.,/]\d+)?)?)\s*({_UNIT})\.?$",
        phrase,
    )
    if suffix:
        return _parse_ingredient_line(
            f"{suffix.group(1).strip()} — {suffix.group(2)} {suffix.group(3)}"
        )

    # «500 грамм творога» — старый формат парсера
    prefix = re.match(
        rf"(?i)^(\d+(?:[.,/]\d+)?(?:\s*[-–]\s*\d+(?:[.,/]\d+)?)?)"
        rf"\s*({_UNIT})\.?\s+(.+)$",
        phrase,
    )
    if prefix:
        return _parse_ingredient_line(phrase)

    return {"name": phrase, "amount": None, "unit": None, "notes": None}


def _split_steps(block: str) -> list[str]:
    block = re.sub(
        r"(?i)^\s*(шаги|приготовление|инструкции|способ приготовления|процесс)"
        r"\s*[:\-—.]?\s*",
        "",
        block.strip(),
    )
    numbered = re.split(r"(?:^|(?<=[.!?])\s+|\n+)\s*\d+[.)]\s+", block)
    if len(numbered) > 1:
        parts = numbered
    else:
        parts = re.split(
            r"(?<=[.!?])\s+|\n+|;\s*|"
            r"\s+(?:потом|затем|далее|после этого)\s+",
            block,
        )
    result = []
    for part in parts:
        value = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", part).strip()
        value = re.sub(r"(?i)^(и|а затем|затем|потом|далее)\s+", "", value)
        value = value.strip(" .;:—-\n\t")
        if len(value) >= 2:
            result.append(value)
    return result


def parse_local(text: str) -> dict[str, Any] | None:
    """Пробует разобрать текст без LLM. None — если структуры не хватило."""
    ing = _SECTION_ING.search(text)
    steps = _SECTION_STEPS.search(text)
    if not ing or not steps:
        return None
    if steps.start() <= ing.end():
        return None

    title = _clean_title(text[: ing.start()])
    if not title:
        return None

    ingredient_phrases = _split_ingredient_phrases(
        text[ing.end(): steps.start()]
    )
    ingredients = [
        parsed
        for phrase in ingredient_phrases
        if (parsed := _parse_ingredient_phrase(phrase))
    ]
    instructions = _split_steps(text[steps.end():])

    if len(ingredients) < 2 or not instructions:
        return None

    return {
        "name": title,
        "description": None,
        "ingredients": ingredients,
        "instructions": instructions,
        "tags": [],
        "source": "voice",
    }


def _extract_json(raw: str) -> dict[str, Any]:
    value = (raw or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        value = value[start: end + 1]
    try:
        data = json.loads(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"LLM вернул не JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM вернул не объект JSON")
    return data


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _clean_llm_recipe(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("LLM не вернул название рецепта")

    ingredients: list[dict[str, Any]] = []
    for item in data.get("ingredients") or []:
        if isinstance(item, str):
            parsed = _parse_ingredient_line(item)
        elif isinstance(item, dict):
            item_name = str(item.get("name") or "").strip()
            if not item_name:
                continue
            parsed = {
                "name": item_name,
                "amount": item.get("amount"),
                "unit": item.get("unit"),
                "notes": item.get("notes"),
            }
        else:
            continue
        if parsed.get("name"):
            parsed["name"] = str(parsed["name"]).strip()
            ingredients.append(parsed)

    instructions = _str_list(data.get("instructions"))
    if not ingredients or not instructions:
        raise ValueError("LLM не вернул ингредиенты или шаги")

    return {
        "name": name,
        "description": data.get("description"),
        "ingredients": ingredients,
        "instructions": instructions,
        "tags": _str_list(data.get("tags")),
        "servings": _int_or_none(data.get("servings")),
        "prep_time": _int_or_none(data.get("prep_time")),
        "cook_time": _int_or_none(data.get("cook_time")),
        "total_time": _int_or_none(data.get("total_time")),
        "source": "voice",
    }


async def parse_with_llm(text: str, user_id: str | None) -> dict[str, Any]:
    from services.llm_cascade import call_llm_cascade

    raw, _provider = await call_llm_cascade(
        user_id=user_id,
        prompt=_PROMPT.format(text=text),
        system=_SYSTEM,
        max_tokens=4000,
        temperature=0.1,
    )
    return _clean_llm_recipe(_extract_json(raw))


async def parse(
    text: str, user_id: str | None
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Возвращает (рецепт, источник разбора, issues обогащения)."""
    local = parse_local(text)
    if local is not None:
        data = local
        source = "local"
    else:
        data = await parse_with_llm(text, user_id)
        source = "llm"

    from services.recipe_normalizer import normalize_recipe

    normalized = normalize_recipe(data)

    issues: list[dict[str, Any]] = []
    try:
        from services.recipe_enricher import enrich_recipe

        enriched, issues = await enrich_recipe(normalized)
        return enriched, source, issues
    except Exception as exc:  # noqa: BLE001
        issues = [{
            "severity": "warning",
            "code": "enrich_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }]
        return normalized, source, issues
