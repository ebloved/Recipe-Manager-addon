"""Адаптация рецептов под аэрогриль через строгий JSON."""
import json
import logging
import re
from typing import Any
from services.generator.providers import get_llm_provider
from services.file_logger import log_llm_event
from stores.settings import settings_store

logger = logging.getLogger(__name__)

AIRFRYER_GUIDE = """
Аэрогриль (корзина 3.8 л, 1500 Вт):
- Температура: минус 10–20 °C от режима духовки.
- Время: минус 20% от рецепта.
- Загрузка: максимум 2/3 корзины, один слой.
- Мясо: крупные куски прикрывать фольгой, мелкие — без.
- Выпечка: снижай t на 15-20°C, прикрывай фольгой.
"""

SYSTEM_PROMPT = (
    "Ты — опытный повар-технолог. Твоя задача — адаптировать шаги рецепта для аэрогриля. "
    "Верни ответ СТРОГО в формате JSON без Markdown-разметки. "
    "Структура: "
    '{"instructions": ["Новый шаг 1", "Новый шаг 2"], "cook_time": 30, "total_time": 40}'
)

async def adapt_recipe_to_airfryer(recipe: dict[str, Any], job_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    from services.auth import users_store
    from services.rate_limiter import rate_limiter
    
    user_key = None
    if user_id:
        conf = users_store.get_llm_config(user_id)
        user_key = conf.get("gemini_api_key")
        
    if not user_key and user_id:
        if not await rate_limiter.can_generate(user_id):
            raise RuntimeError("Достигнут лимит 5 бесплатных генераций в день.")

    provider, provider_name = get_llm_provider()
    if provider is None:
        raise RuntimeError("No LLM provider available")

    prompt = (
        f"Справочник:\n{AIRFRYER_GUIDE}\n\n"
        f"Оригинальный рецепт: {recipe.get('name')}\n"
        f"Время готовки: {recipe.get('cook_time', 'неизвестно')} мин\n"
        f"Шаги:\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(recipe.get("instructions", [])))
    )

    try:
        raw = await provider.complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=int(settings_store.get("adapter_max_tokens", 2000)),
            temperature=0.3,
            job_id=job_id,
            api_key=user_key,
        )
        
        s = raw.strip()
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\n", "", s)
            s = re.sub(r"\n```$", "", s)
        s = s.strip()
        
        idx1 = s.find("{")
        idx2 = s.rfind("}")
        if idx1 >= 0 and idx2 >= 0:
            s = s[idx1:idx2+1]

        data = json.loads(s)
        log_llm_event(job_id, user_id, "adapt_airfryer", "success", raw)
        return data
    except Exception as e:
        log_llm_event(job_id, user_id, "adapt_airfryer", "error", raw if 'raw' in locals() else "", str(e))
        logger.error(f"[adapter] Error: {e}")
        raise RuntimeError(f"Ошибка адаптации: {e}")
