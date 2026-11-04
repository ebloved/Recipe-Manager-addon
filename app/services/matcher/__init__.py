"""Пакет матчинга ингредиентов с продуктами.

Точка входа для `routes/matcher.py`. Вся логика — в подмодулях:

    base.py              — типы и интерфейсы провайдеров
    local_fuzzy.py       — уровень A: exact + fuzzy (Levenshtein + стемминг)
    gemini_embedder.py   — уровень B: эмбеддинги через Gemini
    external_llm.py      — уровень B/C: OpenAI-совместимый endpoint (Hermes и др.)
    local_embedder.py    — уровень B: sentence-transformers (ONNX, CPU)
    providers.py         — реестр провайдеров
    cascade.py           — оркестратор (единственное место, которое знает всё)

Здесь — только реэкспорт функций, которые ожидает routes/matcher.py.
Никакой логики.

Если `cascade.py` ещё не собран (например, во время поэтапной разработки),
импорт падает с понятным сообщением. Routes ловит это и отдаёт 503.
"""
from __future__ import annotations

VERSION = "1.0.0"

__all__ = [
    "VERSION",
    "match_name",
    "match_batch",
    "validate_pair",
    "apply_link_to_recipe",
    "apply_links_to_recipe",
    "status",
    "check_provider",
]


# ---------------------------------------------------------------------------
# Реэкспорт из cascade.py.
#
# Если cascade.py ещё не создан — падаем с понятным ImportError.
# Routes/matcher.py оборачивает этот импорт в try/except и отдаёт 503
# с текстом «модуль матчинга ещё не собран». Это позволяет собирать аддон
# и разрабатывать UI, пока каскад не готов.
# ---------------------------------------------------------------------------

try:
    from .cascade import (  # type: ignore[import]  # noqa: F401
        match_name,
        match_batch,
        validate_pair,
        apply_link_to_recipe,
        apply_links_to_recipe,
        status,
        check_provider,
    )
except ImportError as exc:  # noqa: F841
    raise ImportError(
        "services/matcher/cascade.py не найден. "
        "Каскад матчинга недоступен в этой сборке. "
        "Автоматическая привязка продуктов работать не будет — "
        "связки делаются вручную через UI (вкладка «Продукты»)."
    ) from exc