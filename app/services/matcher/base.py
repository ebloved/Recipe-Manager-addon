"""Базовые типы, интерфейсы и утилиты для каскада матчинга.

Никакой логики — только контракты. Это позволяет:
  - писать провайдеры независимо друг от друга
  - подменять их в тестах моками
  - менять структуру каскада, не трогая провайдеры
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MatchMethod(str, Enum):
    """Каким способом найден результат. Влияет на UI-подсветку и доверие."""
    EXACT = "exact"                  # точное совпадение имени/алиаса
    FUZZY = "fuzzy"                  # Levenshtein + стемминг
    VECTOR = "vector"                # косинусное сходство эмбеддингов
    GENERATIVE = "generative"        # LLM подтвердил связку
    MANUAL = "manual"                # пользователь связал вручную


class ProviderKind(str, Enum):
    FUZZY = "fuzzy"                  # локальный, без сети
    EMBEDDING = "embedding"          # выдаёт вектора
    GENERATIVE = "generative"        # LLM chat/completions


class MatchDecision(str, Enum):
    """Решение каскада по результату."""
    MATCHED = "matched"              # уверенное совпадение, применять сразу
    SUGGEST = "suggest"              # нужна валидация или подтверждение
    NOT_FOUND = "not_found"          # ничего не нашли
    ERROR = "error"                  # все провайдеры упали


# ---------------------------------------------------------------------------
# Конфигурационные типы
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Thresholds:
    """Пороги для принятия решений каскадом.

    auto:    score >= auto    → принимаем без вопросов
    suggest: suggest <= score < auto  → нужна валидация или подтверждение
             score < suggest   → не показываем
    """
    auto: float = 0.95
    suggest: float = 0.80

    def classify(self, score: float) -> MatchDecision:
        if score >= self.auto:
            return MatchDecision.MATCHED
        if score >= self.suggest:
            return MatchDecision.SUGGEST
        return MatchDecision.NOT_FOUND

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Thresholds":
        if not d:
            return cls()
        return cls(
            auto=float(d.get("auto", 0.95)),
            suggest=float(d.get("suggest", 0.80)),
        )


# ---------------------------------------------------------------------------
# Метаданные провайдера
# ---------------------------------------------------------------------------

@dataclass
class ProviderInfo:
    """Состояние провайдера: имя, тип, доступность, здоровье."""
    name: str                          # "local_fuzzy", "gemini", "hermes"
    kind: ProviderKind
    enabled: bool = True
    available: bool = False            # проходил ли health-чек
    priority: int = 100                # меньше = раньше в каскаде
    model_key: str | None = None       # для embedding-провайдеров
    latency_ms: float | None = None    # последний измеренный отклик
    last_check: str | None = None      # ISO timestamp
    error: str | None = None           # текст последней ошибки, если была
    notes: str | None = None           # свободный текст (для UI)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "enabled": self.enabled,
            "available": self.available,
            "priority": self.priority,
            "model_key": self.model_key,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check,
            "error": self.error,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Результаты
# ---------------------------------------------------------------------------

@dataclass
class MatchCandidate:
    """Один кандидат на связку."""
    product_id: str
    name: str
    brand: str | None = None
    barcode: str | None = None
    image_url: str | None = None
    nutrition_per_100g: dict[str, Any] | None = None
    score: float = 0.0
    method: MatchMethod = MatchMethod.EXACT
    provider: str = ""                 # какой провайдер дал этот score
    matched_alias: str | None = None   # через какой алиас нашли

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "brand": self.brand,
            "barcode": self.barcode,
            "image_url": self.image_url,
            "nutrition_per_100g": self.nutrition_per_100g,
            "score": round(self.score, 4),
            "method": self.method.value,
            "provider": self.provider,
            "matched_alias": self.matched_alias,
        }


@dataclass
class MatchResult:
    """Полный результат матчинга одного имени."""
    query: str
    normalized: str
    decision: MatchDecision
    match: MatchCandidate | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)
    from_cache: bool = False
    error: str | None = None

    @property
    def needs_confirmation(self) -> bool:
        return self.decision == MatchDecision.SUGGEST

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "normalized": self.normalized,
            "decision": self.decision.value,
            "match": self.match.to_dict() if self.match else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "needs_confirmation": self.needs_confirmation,
            "from_cache": self.from_cache,
            "error": self.error,
        }


@dataclass
class ValidationResult:
    """Результат генеративной валидации пары (имя, продукт)."""
    valid: bool | None = None          # None = не смогли определить
    provider: str | None = None
    confidence: float | None = None
    reason: str | None = None
    from_cache: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "provider": self.provider,
            "confidence": self.confidence,
            "reason": self.reason,
            "from_cache": self.from_cache,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Исключения
# ---------------------------------------------------------------------------

class MatcherError(Exception):
    """Базовая ошибка матчинга."""


class ProviderUnavailable(MatcherError):
    """Провайдер недоступен (сеть, ключ, timeout)."""


class RateLimited(MatcherError):
    """Провайдер вернул 429 или сработал локальный дневной лимит."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Интерфейсы провайдеров
# ---------------------------------------------------------------------------

class FuzzyMatcher(ABC):
    """Локальный матчер без сети: exact + Levenshtein + стемминг."""

    name: str = "fuzzy"

    @abstractmethod
    def find(
        self,
        query: str,
        products: Sequence[dict[str, Any]],
        limit: int = 5,
    ) -> list[MatchCandidate]:
        """Возвращает отсортированных кандидатов (по убыванию score).

        products — список «сырых» продуктов из ingredients_store.
        Реализация не сохраняет состояние и не делает I/O.
        """

    @abstractmethod
    async def health(self) -> ProviderInfo:
        """Проверка готовности. Для локального fuzzy — всегда available=True."""


class EmbeddingProvider(ABC):
    """Провайдер векторных представлений текста.

    Возвращает list[list[float]], по одному вектору на каждый текст.
    Вектора нормализованы к единичной длине — так проще считать cosine similarity.
    """

    name: str = ""
    model_key: str = ""                # "gemini-embedding-001:768"

    # «Фоновое» косинусное сходство между семантически далёкими текстами.
    #
    # У разных моделей оно разное:
    #   - OpenAI text-embedding-3: ~0.0–0.2
    #   - sentence-transformers MiniLM: ~0.0–0.3
    #   - Gemini embedding-001: ~0.75 (модель «сжимает» все тексты
    #     в узкий конус, поэтому даже случайные пары дают 0.6–0.85)
    #
    # Каскад использует это значение, чтобы нормализовать score:
    #   adjusted = (raw - baseline) / (1 - baseline)
    #
    # Без нормализации Gemini будет давать 0.85 для «чтотонесуществующее»
    # и «вода», что превышает порог suggest и создаёт мусорные кандидаты.
    baseline_similarity: float = 0.0

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает вектора для списка текстов.

        Реализация обязана:
          - вернуть ровно len(texts) векторов
          - нормализовать каждый вектор к длине 1
          - выбросить ProviderUnavailable при ошибке сети/ключа
        """

    @abstractmethod
    async def health(self) -> ProviderInfo:
        """Проверка: доступен ли провайдер сейчас."""

    async def embed_chunked(
        self,
        texts: list[str],
        chunk_size: int = 20,
        on_progress: Any = None,
    ) -> list[list[float]]:
        """Батчит большие списки. По умолчанию — просто вызывает embed().

        Провайдеры с ограничениями (Gemini 15 RPM) могут переопределить,
        чтобы вставить паузу между чанками.
        """
        out: list[list[float]] = []
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            vectors = await self.embed(chunk)
            out.extend(vectors)
            if on_progress:
                on_progress(len(out), len(texts))
        return out


class GenerativeProvider(ABC):
    """LLM-провайдер для генеративной валидации.

    Используется только на уровне C (спорные пары). Не вызывается
    для каждого ингредиента — иначе лимиты сгорят за день.
    """

    name: str = ""
    model: str = ""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 200,
        temperature: float = 0.0,
    ) -> str:
        """Отправляет запрос и возвращает текст ответа.

        Бросает ProviderUnavailable при ошибке.
        """

    @abstractmethod
    async def health(self) -> ProviderInfo:
        """Проверка доступности."""


# ---------------------------------------------------------------------------
# Утилиты (чистые функции, без I/O)
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Приводит имя ингредиента к нормализованному виду.

    - lowercase
    - ё → е
    - схлопывание пробелов
    - удаление обрамляющих пробелов
    - удаление финальных знаков пунктуации

    НЕ убирает стоп-слова и НЕ делает стемминг — это задача fuzzy-матчера.
    """
    if not name:
        return ""
    s = str(name).strip().lower().replace("ё", "е")
    s = " ".join(s.split())                    # схлопнуть пробелы
    s = s.strip(".,;:!?()[]{}\"'«»").strip()
    return s


def make_model_key(provider: str, model: str, dim: int) -> str:
    """Стандартный ключ для хранения векторов.

    Пример: 'gemini:gemini-embedding-001:768'
    """
    return f"{provider}:{model}:{dim}"


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Косинусное сходство для нормализованных векторов.

    Для нормализованных (unit length) векторов это просто dot product.
    Для ненормализованных — полная формула.

    Возвращает значение в диапазоне [-1, 1].
    """
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        raise ValueError(f"Vector dimensions mismatch: {len(a)} vs {len(b)}")

    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y

    if na == 0.0 or nb == 0.0:
        return 0.0

    return dot / (math.sqrt(na) * math.sqrt(nb))


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    """Разбивает iterable на чанки заданного размера."""
    buf: list[Any] = []
    for x in items:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def top_n(
    candidates: Iterable[MatchCandidate],
    n: int,
    min_score: float = 0.0,
) -> list[MatchCandidate]:
    """Возвращает top-N кандидатов с сортировкой по score убыванию."""
    filtered = [c for c in candidates if c.score >= min_score]
    filtered.sort(key=lambda c: (-c.score, c.name or ""))
    return filtered[:n]