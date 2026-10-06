"""Провайдер Gemini: эмбеддинги + генеративная валидация.

Реализует два интерфейса сразу:
  - EmbeddingProvider   (embed)
  - GenerativeProvider  (complete)

Это удобно для каскада: один объект закрывает и уровень B (эмбеддинги),
и уровень C (генеративная валидация).

API:
  Эмбеддинги:  POST /v1beta/models/{model}:batchEmbedContents
  Генерация:   POST /v1beta/models/{model}:generateContent

Бесплатный лимит Gemini (2026): ~15 RPM на эмбеддингах, поэтому
embed_chunked переопределён — вставляет паузу между чанками.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import httpx

from config import (
    GEMINI_API_KEY,
    GEMINI_MODELS,
    GEMINI_PROXY,
)

from .base import (
    EmbeddingProvider,
    GenerativeProvider,
    ProviderInfo,
    ProviderKind,
    ProviderUnavailable,
    RateLimited,
)


_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Модель эмбеддингов и её размерность.
# gemini-embedding-001 — актуальная модель (заменила text-embedding-004).
_EMBEDDING_MODEL = "gemini-embedding-001"
_EMBEDDING_DIM = 768

# Модель для генеративной валидации — самая быстрая из доступных.
_GENERATIVE_FALLBACK_MODEL = "gemini-2.0-flash"

# Лимит на batch-запрос к эмбеддингам (официально до 100, но на free tier
# безопаснее меньше, чтобы не ловить 400 на переразмеренных запросах).
_EMBED_BATCH_LIMIT = 20

# Gemini free tier: 15 RPM на эмбеддингах.
# Между чанками выдерживаем паузу, чтобы не словить 429.
_CHUNK_DELAY_SEC = 4.2

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class GeminiProvider(EmbeddingProvider, GenerativeProvider):
    """Провайдер Gemini: эмбеддинги + chat."""

    name = "gemini"
    model = _GENERATIVE_FALLBACK_MODEL
    model_key = f"gemini:{_EMBEDDING_MODEL}:{_EMBEDDING_DIM}"

    def __init__(self) -> None:
        self._api_key = GEMINI_API_KEY
        self._proxy = GEMINI_PROXY
        self._generative_model = (
            GEMINI_MODELS[0] if GEMINI_MODELS else _GENERATIVE_FALLBACK_MODEL
        )

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает нормализованные эмбеддинги для списка текстов."""
        if not self._api_key:
            raise ProviderUnavailable("GEMINI_API_KEY не задан")

        clean = [t if t else " " for t in texts]
        if not clean:
            return []

        url = f"{_API_BASE}/models/{_EMBEDDING_MODEL}:batchEmbedContents"
        payload = {
            "requests": [
                {
                    "model": f"models/{_EMBEDDING_MODEL}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": "SEMANTIC_SIMILARITY",
                }
                for t in clean
            ]
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        client_kwargs: dict = {"timeout": _TIMEOUT}
        if self._proxy:
            client_kwargs["proxy"] = self._proxy

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"Gemini timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"Gemini network error: {exc}") from exc

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited("Gemini: 429 Too Many Requests", retry_after=retry_after)
        if resp.status_code == 401 or resp.status_code == 403:
            raise ProviderUnavailable(f"Gemini: auth failed ({resp.status_code})")
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"Gemini: server error {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"Gemini: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(f"Gemini: bad JSON — {exc}") from exc

        embeddings = data.get("embeddings") or []
        if len(embeddings) != len(clean):
            raise ProviderUnavailable(
                f"Gemini: returned {len(embeddings)} vectors, expected {len(clean)}"
            )

        out: list[list[float]] = []
        for e in embeddings:
            vec = e.get("values") or []
            if not vec:
                # битый вектор — спасём позицию нулевым
                vec = [0.0] * _EMBEDDING_DIM
            out.append(_normalize(vec))
        return out

    async def embed_chunked(
        self,
        texts: list[str],
        chunk_size: int = _EMBED_BATCH_LIMIT,
        on_progress=None,
    ) -> list[list[float]]:
        """Батчит эмбеддинги с паузой между чанками (free tier ~15 RPM)."""
        if not texts:
            return []

        out: list[list[float]] = []
        chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]

        for idx, chunk in enumerate(chunks):
            vectors = await self.embed(chunk)
            out.extend(vectors)
            if on_progress:
                try:
                    on_progress(len(out), len(texts))
                except Exception:  # noqa: BLE001
                    pass
            # пауза между чанками, кроме последнего
            if idx < len(chunks) - 1:
                await asyncio.sleep(_CHUNK_DELAY_SEC)

        return out

    # ------------------------------------------------------------------
    # Generative
    # ------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 200,
        temperature: float = 0.0,
    ) -> str:
        """Отправляет запрос в generateContent и возвращает текст ответа."""
        if not self._api_key:
            raise ProviderUnavailable("GEMINI_API_KEY не задан")

        url = f"{_API_BASE}/models/{self._generative_model}:generateContent"
        body: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": int(max_tokens),
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        client_kwargs: dict = {"timeout": _TIMEOUT}
        if self._proxy:
            client_kwargs["proxy"] = self._proxy

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"Gemini timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"Gemini network error: {exc}") from exc

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited("Gemini: 429 Too Many Requests", retry_after=retry_after)
        if resp.status_code in (401, 403):
            raise ProviderUnavailable(f"Gemini: auth failed ({resp.status_code})")
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"Gemini: server error {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"Gemini: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(f"Gemini: bad JSON — {exc}") from exc

        try:
            candidates = data.get("candidates") or []
            parts = candidates[0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            # Иногда Gemini возвращает пустой ответ из-за safety-фильтра
            return ""

        return text.strip()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> ProviderInfo:
        """Быстрая проверка: ключ задан и API отвечает на минимальный запрос."""
        now = datetime.now(timezone.utc).isoformat()

        if not self._api_key:
            return ProviderInfo(
                name=self.name,
                kind=ProviderKind.EMBEDDING,
                enabled=True,
                available=False,
                priority=40,
                model_key=self.model_key,
                last_check=now,
                error="GEMINI_API_KEY не задан",
            )

        started = datetime.now(timezone.utc)
        url = f"{_API_BASE}/models/{_EMBEDDING_MODEL}:embedContent"
        payload = {
            "model": f"models/{_EMBEDDING_MODEL}",
            "content": {"parts": [{"text": "ping"}]},
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        client_kwargs: dict = {"timeout": httpx.Timeout(10.0)}
        if self._proxy:
            client_kwargs["proxy"] = self._proxy

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return ProviderInfo(
                name=self.name, kind=ProviderKind.EMBEDDING,
                enabled=True, available=False, priority=40,
                model_key=self.model_key, last_check=now,
                error=f"network: {exc}",
            )

        latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000

        if resp.status_code == 200:
            return ProviderInfo(
                name=self.name, kind=ProviderKind.EMBEDDING,
                enabled=True, available=True, priority=40,
                model_key=self.model_key,
                latency_ms=round(latency_ms, 1),
                last_check=now,
                notes=f"embed={_EMBEDDING_MODEL}, chat={self._generative_model}",
            )

        if resp.status_code == 429:
            return ProviderInfo(
                name=self.name, kind=ProviderKind.EMBEDDING,
                enabled=True, available=True, priority=40,
                model_key=self.model_key, last_check=now,
                latency_ms=round(latency_ms, 1),
                error="rate limited (429)",
                notes="ключ рабочий, но лимит исчерпан",
            )

        if resp.status_code in (401, 403):
            err = "неверный GEMINI_API_KEY"
        else:
            err = f"HTTP {resp.status_code}: {resp.text[:120]}"

        return ProviderInfo(
            name=self.name, kind=ProviderKind.EMBEDDING,
            enabled=True, available=False, priority=40,
            model_key=self.model_key,
            latency_ms=round(latency_ms, 1),
            last_check=now,
            error=err,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(vec: list[float]) -> list[float]:
    """Приводит вектор к единичной длине. Если нулевой — возвращает как есть."""
    s = 0.0
    for x in vec:
        s += float(x) * float(x)
    if s <= 0.0:
        return [float(x) for x in vec]
    n = math.sqrt(s)
    return [float(x) / n for x in vec]


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

gemini_embedder = GeminiProvider()