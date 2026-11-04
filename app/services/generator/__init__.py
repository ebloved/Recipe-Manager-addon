"""Пакет генерации рецептов через LLM.

Публичное API:
    generate_suggestions(...) → list[dict]   # оркестратор
    build_prompt(...)         → tuple[str, str]  # (system, user)
    get_llm_provider()        → provider | None
"""
from .generator import generate_suggestions
from .prompt import build_prompt
from .providers import get_llm_provider, get_providers_status

__all__ = [
    "generate_suggestions",
    "build_prompt",
    "get_llm_provider",
    "get_providers_status",
]
