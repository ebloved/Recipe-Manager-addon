"""Реестр провайдеров матчинга.

Центральная точка, которая знает обо всех доступных провайдерах и умеет:
  - возвращать их по приоритету для заданной задачи (embedding / generative)
  - включать и отключать отдельные провайдеры на лету (без перезапуска)
  - подменять провайдеров в тестах (mock)
  - собирать сводный статус

Каскад (cascade.py) обращается сюда, а не импортирует провайдеров напрямую.
Это развязывает логику и упрощает тестирование.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from config import (
    GEMINI_API_KEY,
    LOCAL_EMBEDDER_ENABLED,
    MATCHER_EXTERNAL_EMBEDDING_MODEL,
    MATCHER_EXTERNAL_ENABLED,
    MATCHER_EXTERNAL_URL,
)

from .base import (
    EmbeddingProvider,
    FuzzyMatcher,
    GenerativeProvider,
    ProviderInfo,
    ProviderKind,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Записи реестра
# ---------------------------------------------------------------------------

@dataclass
class ProviderEntry:
    """Обёртка над провайдером: даёт реестру понять, что с ним делать."""
    name: str
    instance: Any
    kinds: tuple[ProviderKind, ...]        # какие интерфейсы реализует
    priority: int                          # меньше — раньше в каскаде
    enabled_by_config: bool = True         # включён ли по конфигу
    enabled_by_user: bool = True           # можно ли отключить на лету
    notes: str | None = None

    def supports(self, kind: ProviderKind) -> bool:
        return kind in self.kinds

    def effective_enabled(self) -> bool:
        return self.enabled_by_config and self.enabled_by_user


# ---------------------------------------------------------------------------
# Реестр
# ---------------------------------------------------------------------------

class ProviderRegistry:
    """Держит все провайдеры и фильтрует их по задаче."""

    def __init__(self) -> None:
        self._entries: list[ProviderEntry] = []
        self._by_name: dict[str, ProviderEntry] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Регистрирует провайдеров. Идемпотентно.

        Вызывается лениво при первом обращении каскада, а не при импорте
        модуля, чтобы избежать циклических импортов и медленного старта.
        """
        if self._initialized:
            return
        self._initialized = True

        # --- Локальный fuzzy: всегда включён ---
        try:
            from .local_fuzzy import local_fuzzy_matcher
            self.register(ProviderEntry(
                name=local_fuzzy_matcher.name,
                instance=local_fuzzy_matcher,
                kinds=(ProviderKind.FUZZY,),
                priority=10,
                enabled_by_config=True,
                notes="Локальный, без сети",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("local_fuzzy недоступен: %s", exc)

        # --- Внешний OpenAI-совместимый endpoint (Hermes/OpenRouter/Ollama/...) ---
        try:
            from .external_llm import external_llm
            kinds: list[ProviderKind] = [ProviderKind.GENERATIVE]
            if MATCHER_EXTERNAL_EMBEDDING_MODEL:
                kinds.append(ProviderKind.EMBEDDING)

            self.register(ProviderEntry(
                name=external_llm.name,
                instance=external_llm,
                kinds=tuple(kinds),
                priority=20,
                enabled_by_config=bool(MATCHER_EXTERNAL_ENABLED and MATCHER_EXTERNAL_URL),
                notes=f"{MATCHER_EXTERNAL_URL or '—'} ({external_llm.chat_model})",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("external_llm недоступен: %s", exc)

        # --- Локальный sentence-transformers ---
        try:
            from .local_embedder import local_embedder
            self.register(ProviderEntry(
                name=local_embedder.name,
                instance=local_embedder,
                kinds=(ProviderKind.EMBEDDING,),
                priority=30,
                enabled_by_config=bool(LOCAL_EMBEDDER_ENABLED),
                notes="sentence-transformers, CPU",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("local_embedder недоступен: %s", exc)

        # --- Gemini ---
        try:
            from .gemini_embedder import gemini_embedder
            self.register(ProviderEntry(
                name=gemini_embedder.name,
                instance=gemini_embedder,
                kinds=(ProviderKind.EMBEDDING, ProviderKind.GENERATIVE),
                priority=40,
                enabled_by_config=bool(GEMINI_API_KEY),
                notes="gemini-embedding-001 + chat",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini_embedder недоступен: %s", exc)

        logger.info(
            "ProviderRegistry инициализирован: %d провайдеров (%s)",
            len(self._entries),
            ", ".join(e.name for e in self._entries),
        )

    # ------------------------------------------------------------------
    # Регистрация / дерегистрация
    # ------------------------------------------------------------------

    def register(self, entry: ProviderEntry) -> None:
        """Добавляет провайдера. При совпадении имени — заменяет."""
        if entry.name in self._by_name:
            self._entries = [e for e in self._entries if e.name != entry.name]
        self._entries.append(entry)
        self._by_name[entry.name] = entry

    def unregister(self, name: str) -> bool:
        """Убирает провайдера. Возвращает True, если был."""
        entry = self._by_name.pop(name, None)
        if not entry:
            return False
        self._entries = [e for e in self._entries if e.name != name]
        return True

    def clear(self) -> None:
        """Полная очистка. Для тестов."""
        self._entries.clear()
        self._by_name.clear()
        self._initialized = False

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, name: str) -> ProviderEntry | None:
        self.initialize()
        return self._by_name.get(name)

    def all(self) -> list[ProviderEntry]:
        self.initialize()
        return list(self._entries)

    def enabled(self) -> list[ProviderEntry]:
        self.initialize()
        return [e for e in self._entries if e.effective_enabled()]

    def by_kind(self, kind: ProviderKind, only_enabled: bool = True) -> list[ProviderEntry]:
        """Возвращает провайдеров заданного типа, отсортированных по приоритету."""
        self.initialize()
        out = [
            e for e in self._entries
            if e.supports(kind) and (not only_enabled or e.effective_enabled())
        ]
        out.sort(key=lambda e: e.priority)
        return out

    def embedding_providers(self, only_enabled: bool = True) -> list[ProviderEntry]:
        return self.by_kind(ProviderKind.EMBEDDING, only_enabled=only_enabled)

    def generative_providers(self, only_enabled: bool = True) -> list[ProviderEntry]:
        return self.by_kind(ProviderKind.GENERATIVE, only_enabled=only_enabled)

    def fuzzy_matchers(self, only_enabled: bool = True) -> list[ProviderEntry]:
        return self.by_kind(ProviderKind.FUZZY, only_enabled=only_enabled)

    # ------------------------------------------------------------------
    # Управление на лету
    # ------------------------------------------------------------------

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Включает/отключает провайдера. Возвращает True, если нашли."""
        entry = self._by_name.get(name)
        if not entry:
            return False
        entry.enabled_by_user = bool(enabled)
        logger.info(
            "Провайдер '%s' %s пользователем",
            name, "включён" if enabled else "отключён",
        )
        return True

    # ------------------------------------------------------------------
    # Статус
    # ------------------------------------------------------------------

    async def health_all(self) -> list[dict[str, Any]]:
        """Собирает health-статус всех провайдеров параллельно."""
        import asyncio

        entries = self.all()

        async def _one(entry: ProviderEntry) -> dict[str, Any]:
            if not entry.effective_enabled():
                # Не опрашиваем — просто отдаём «выключен»
                return ProviderInfo(
                    name=entry.name,
                    kind=entry.kinds[0] if entry.kinds else ProviderKind.FUZZY,
                    enabled=False,
                    available=False,
                    priority=entry.priority,
                    notes=entry.notes,
                ).to_dict()

            try:
                health_method = getattr(entry.instance, "health", None)
                if not callable(health_method):
                    return ProviderInfo(
                        name=entry.name,
                        kind=entry.kinds[0] if entry.kinds else ProviderKind.FUZZY,
                        enabled=True,
                        available=True,
                        priority=entry.priority,
                        notes=entry.notes,
                    ).to_dict()
                info = await health_method()
                # Гарантируем, что name/priority совпадают с реестром
                info.name = entry.name
                info.priority = entry.priority
                if entry.notes and not info.notes:
                    info.notes = entry.notes
                return info.to_dict()
            except Exception as exc:  # noqa: BLE001
                return ProviderInfo(
                    name=entry.name,
                    kind=entry.kinds[0] if entry.kinds else ProviderKind.FUZZY,
                    enabled=True,
                    available=False,
                    priority=entry.priority,
                    last_check=datetime.now(timezone.utc).isoformat(),
                    error=str(exc),
                ).to_dict()

        results = await asyncio.gather(*[_one(e) for e in entries])
        results.sort(key=lambda d: d.get("priority", 100))
        return results

    def snapshot(self) -> dict[str, Any]:
        """Быстрый синхронный снимок реестра. Без health-запросов."""
        self.initialize()
        return {
            "count": len(self._entries),
            "providers": [
                {
                    "name": e.name,
                    "kinds": [k.value for k in e.kinds],
                    "priority": e.priority,
                    "enabled_by_config": e.enabled_by_config,
                    "enabled_by_user": e.enabled_by_user,
                    "effective_enabled": e.effective_enabled(),
                    "notes": e.notes,
                }
                for e in sorted(self._entries, key=lambda x: x.priority)
            ],
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

provider_registry = ProviderRegistry()