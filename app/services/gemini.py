"""Обёртка над Gemini API."""
from __future__ import annotations

import asyncio
import re

import httpx
from fastapi import HTTPException

from config import (
    GEMINI_API_KEY,
    GEMINI_MODELS,
    GEMINI_PROXY,
    TEMPLATE_FILE,
)

_TEMPLATE_CACHE: str | None = None


def _load_template() -> str:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        if TEMPLATE_FILE.exists():
            _TEMPLATE_CACHE = TEMPLATE_FILE.read_text(encoding="utf-8")
            print(f"[template] loaded from {TEMPLATE_FILE}")
        else:
            _TEMPLATE_CACHE = ""
            print(f"[template] NOT FOUND at {TEMPLATE_FILE}")
    return _TEMPLATE_CACHE


RECIPE_PROMPT = """Ты — редактор кулинарных рецептов.

Тебе дан текст из субтитров YouTube Shorts (возможно, с ошибками распознавания речи) и пример правильно оформленного рецепта в формате YAML front matter + Markdown.

Оформи результат в ТОЧНО ТАКОЙ ЖЕ структуре, как в примере ниже:
- тот же набор полей в YAML front matter;
- та же разбивка на секции (Ингредиенты / Шаги / Заметки);
- тот же стиль записи количеств («500 г», «2 ст. л.», «по вкусу»);
- те же ключи nutrition, если есть данные.

Жёсткие правила:
1. Исправляй только очевидные ошибки распознавания речи.
2. НЕ выдумывай ингредиенты, количества, время, температуру и названия блюд, которых нет в тексте.
3. Если каких-то полей нет — ставь `null` в YAML или «не указано» в тексте.
4. Верни ТОЛЬКО итоговый Markdown, без пояснений и без обрамляющих ```.

Пример оформления:

{template}

Текст субтитров:

{text}
"""


async def call_gemini(text: str, user_id: str | None = None) -> tuple[str, str]:
    """Генерирует Markdown-рецепт по субтитрам через LLM-каскад."""
    from services.llm_cascade import call_llm_cascade

    template = _load_template()
    prompt = RECIPE_PROMPT.format(template=template, text=text)

    try:
        raw, provider_name = await call_llm_cascade(
            user_id=user_id,
            prompt=prompt,
            system=None,
            max_tokens=2000,
            temperature=0.2,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Все модели недоступны: {exc}")

    markdown = (raw or "").strip()
    if markdown.startswith("```"):
        markdown = re.sub(r"^```[a-zA-Z]*\n", "", markdown)
        markdown = re.sub(r"\n```$", "", markdown)
    return markdown.strip(), provider_name