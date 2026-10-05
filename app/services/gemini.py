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


async def call_gemini(text: str) -> tuple[str, str]:
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY не задан в настройках add-on")

    template = _load_template()
    prompt = RECIPE_PROMPT.format(template=template, text=text)

    last_error: Exception | None = None
    client_kwargs: dict = {"timeout": 60.0}
    if GEMINI_PROXY:
        client_kwargs["proxy"] = GEMINI_PROXY

    async with httpx.AsyncClient(**client_kwargs) as client:
        for model in GEMINI_MODELS:
            for attempt in range(1, 4):
                try:
                    url = (
                        "https://generativelanguage.googleapis.com/v1beta/"
                        f"models/{model}:generateContent?key={GEMINI_API_KEY}"
                    )
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000},
                    }
                    resp = await client.post(url, json=payload)
                    if resp.status_code in (503, 429):
                        raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
                    resp.raise_for_status()
                    data = resp.json()
                    markdown = (
                        data["candidates"][0]["content"]["parts"][0]["text"]
                    ).strip()
                    if markdown.startswith("```"):
                        markdown = re.sub(r"^```[a-zA-Z]*\n", "", markdown)
                        markdown = re.sub(r"\n```$", "", markdown)
                    return markdown.strip(), model
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    print(f"[gemini] model={model} attempt={attempt} failed: {e}")
                    if attempt < 3:
                        await asyncio.sleep(2**attempt)
    raise HTTPException(502, f"Все модели недоступны: {last_error}")