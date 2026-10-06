"""Универсальный OpenAI-совместимый провайдер.

Работает с любым сервисом, который предоставляет endpoint-ы в стиле OpenAI:
  POST {base_url}/chat/completions
  POST {base_url}/embeddings

Проверено на: Hermes, OpenRouter, Groq, Ollama, LM Studio, vLLM, llama.cpp server.
Отличаются только base_url, api_key и имена моделей — всё остальное одинаково.

Особенности:
  - Один класс — оба интерфейса (EmbeddingProvider + GenerativeProvider)
  - Эмбеддинги включаются опционально (если MATCHER_EXTERNAL_EMBEDDING_MODEL задан)
  - Работает без api_key (Ollama и локальные сервера часто не требуют Bearer)
  - Дополнительный заголовок x-opencode-session для OpenCode Go, если нужно
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

import httpx

from config import (
    MATCHER_EXTERNAL_EMBEDDING_MODEL,
    MATCHER_EXTERNAL_ENABLED,
    MATCHER_EXTERNAL_KEY,
    MATCHER_EXTERNAL_MODEL,
    MATCHER_EXTERNAL_TIMEOUT,
    MATCHER_EXTERNAL_URL,
)

from .base import (
    EmbeddingProvider,
    GenerativeProvider,
    ProviderInfo,
    ProviderKind,
    ProviderUnavailable,
    RateLimited,
)


# Единый таймаут на все запросы. Отдельно connect — чтобы сразу
# отваливаться, если сервер вообще недоступен.
def _make_timeout() -> httpx.Timeout:
    t = float(MATCHER_EXTERNAL_TIMEOUT or 15.0)
    return httpx.Timeout(t, connect=min(5.0, t))


class ExternalLLMProvider(EmbeddingProvider, GenerativeProvider):
    """Универсальный клиент к OpenAI-совместимому API."""

    name = "hermes"  # отображаемое имя в UI; фактически это «внешний endpoint»

    def __init__(self) -> None:
        self._base_url = (MATCHER_EXTERNAL_URL or "").rstrip("/")
        self._api_key = MATCHER_EXTERNAL_KEY or ""
        self._chat_model = MATCHER_EXTERNAL_MODEL or "hermes-agent"
        self._embed_model = MATCHER_EXTERNAL_EMBEDDING_MODEL or ""
        self._session_id = uuid.uuid4().hex  # для x-opencode-session (безвреден для остальных)

        # model_key для хранения векторов. Используем имя модели из конфига,
        # но не знаем её размерность заранее. Первый успешный embed определит
        # реальную размерность, а ключ будет "hermes:<model>:<dim>".
        # Пока dim=0 — это означает «ещё не известно». После первого вызова
        # dim обновится в instance.
        self._embed_dim: int = 0
        self.model_key = self._build_model_key()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(MATCHER_EXTERNAL_ENABLED and self._base_url)

    @property
    def chat_model(self) -> str:
        return self._chat_model

    def _build_model_key(self) -> str:
        dim = self._embed_dim or 0
        return f"hermes:{self._embed_model or 'no-embed'}:{dim}"

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Некоторые прокси (OpenCode Go) требуют стабильный session ID.
            # Для остальных сервисов это необязательный заголовок.
            "x-opencode-session": self._session_id,
        }
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает нормализованные эмбеддинги.

        Работает только если MATCHER_EXTERNAL_EMBEDDING_MODEL задан.
        Если модель не задана — провайдер используется только для chat.
        """
        if not self.enabled:
            raise ProviderUnavailable("External endpoint не включён")
        if not self._embed_model:
            raise ProviderUnavailable(
                "matcher_external_embedding_model не задан — "
                "эмбеддинги через внешний endpoint недоступны"
            )

        clean = [t if t else " " for t in texts]
        if not clean:
            return []

        url = f"{self._base_url}/embeddings"
        payload = {
            "model": self._embed_model,
            "input": clean,
            # encoding_format=float — стандарт; некоторые сервисы понимают base64,
            # но нам проще работать с float-ами.
            "encoding_format": "float",
        }

        try:
            async with httpx.AsyncClient(timeout=_make_timeout()) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"External embeddings timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"External embeddings network: {exc}") from exc

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited("External: 429 Too Many Requests", retry_after=retry_after)
        if resp.status_code in (401, 403):
            raise ProviderUnavailable(f"External: auth failed ({resp.status_code})")
        if resp.status_code == 404:
            raise ProviderUnavailable(
                f"External: endpoint {url} не найден. "
                f"Проверьте matcher_external_url и наличие embeddings-API."
            )
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"External: server error {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"External: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(f"External: bad JSON — {exc}") from exc

        items = data.get("data") or []
        if len(items) != len(clean):
            raise ProviderUnavailable(
                f"External: returned {len(items)} vectors, expected {len(clean)}"
            )

        # Сортируем по index — некоторые сервисы возвращают не по порядку.
        items.sort(key=lambda x: x.get("index", 0))

        out: list[list[float]] = []
        for it in items:
            vec = it.get("embedding") or []
            if not vec:
                vec = [0.0] * (self._embed_dim or 0) or [0.0]
            out.append(_normalize(vec))

        # Запоминаем реальную размерность (первый успешный вызов).
        if self._embed_dim == 0 and out:
            self._embed_dim = len(out[0])
            self.model_key = self._build_model_key()

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
        """Отправляет chat-запрос и возвращает текст ответа."""
        if not self.enabled:
            raise ProviderUnavailable("External endpoint не включён")

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        url = f"{self._base_url}/chat/completions"
        payload: dict = {
            "model": self._chat_model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=_make_timeout()) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"External chat timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"External chat network: {exc}") from exc

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited("External: 429 Too Many Requests", retry_after=retry_after)
        if resp.status_code in (401, 403):
            raise ProviderUnavailable(f"External: auth failed ({resp.status_code})")
        if resp.status_code == 404:
            raise ProviderUnavailable(
                f"External: endpoint {url} не найден. "
                f"Проверьте matcher_external_url."
            )
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"External: server error {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"External: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(f"External: bad JSON — {exc}") from exc

        try:
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            if isinstance(content, list):
                # Некоторые провайдеры (Anthropic-style) отдают content как список блоков
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text") or "")
                    elif isinstance(block, str):
                        parts.append(block)
                content = "".join(parts)
        except (KeyError, IndexError, TypeError):
            return ""

        return str(content).strip()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> ProviderInfo:
        """Проверяет доступность через GET /models или лёгкий chat-запрос."""
        now = datetime.now(timezone.utc).isoformat()

        if not self.enabled:
            return ProviderInfo(
                name=self.name,
                kind=ProviderKind.GENERATIVE,
                enabled=False,
                available=False,
                priority=20,
                model_key=self._chat_model,
                last_check=now,
                notes="matcher_external_enabled=false",
            )

        if not self._base_url:
            return ProviderInfo(
                name=self.name, kind=ProviderKind.GENERATIVE,
                enabled=True, available=False, priority=20,
                model_key=self._chat_model, last_check=now,
                error="matcher_external_url не задан",
            )

        started = datetime.now(timezone.utc)
        url = f"{self._base_url}/models"

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            return ProviderInfo(
                name=self.name, kind=ProviderKind.GENERATIVE,
                enabled=True, available=False, priority=20,
                model_key=self._chat_model, last_check=now,
                error=f"network: {exc}",
            )

        latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000

        # 200 — всё ок. Некоторые сервисы (Ollama) не отдают /models в
        # OpenAI-формате, но отвечают 200 — этого достаточно.
        if resp.status_code == 200:
            models: list[str] = []
            try:
                data = resp.json()
                models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            except Exception:  # noqa: BLE001
                pass

            notes = f"chat={self._chat_model}"
            if self._embed_model:
                notes += f", embed={self._embed_model}"

            return ProviderInfo(
                name=self.name, kind=ProviderKind.GENERATIVE,
                enabled=True, available=True, priority=20,
                model_key=self._chat_model,
                latency_ms=round(latency_ms, 1),
                last_check=now,
                notes=notes,
            )

        # 404 — некоторые локальные сервисы не имеют /models, но /chat/completions работает.
        # Тогда считаем, что сервер жив, но проверить не получилось.
        if resp.status_code == 404:
            return ProviderInfo(
                name=self.name, kind=ProviderKind.GENERATIVE,
                enabled=True, available=True, priority=20,
                model_key=self._chat_model,
                latency_ms=round(latency_ms, 1),
                last_check=now,
                notes=f"{self._chat_model} (/models отсутствует, но это норма для локальных)",
            )

        if resp.status_code in (401, 403):
            err = "неверный matcher_external_key"
        elif resp.status_code == 429:
            # Не ошибка конфигурации, просто лимит
            return ProviderInfo(
                name=self.name, kind=ProviderKind.GENERATIVE,
                enabled=True, available=True, priority=20,
                model_key=self._chat_model,
                latency_ms=round(latency_ms, 1),
                last_check=now,
                error="rate limited (429)",
                notes="сервер жив, но лимит исчерпан",
            )
        else:
            err = f"HTTP {resp.status_code}: {resp.text[:120]}"

        return ProviderInfo(
            name=self.name, kind=ProviderKind.GENERATIVE,
            enabled=True, available=False, priority=20,
            model_key=self._chat_model,
            latency_ms=round(latency_ms, 1),
            last_check=now,
            error=err,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(vec: list[float]) -> list[float]:
    """Приводит вектор к единичной длине. Нулевые — возвращает как есть."""
    s = 0.0
    for x in vec:
        try:
            s += float(x) * float(x)
        except (TypeError, ValueError):
            return [float(v) if v is not None else 0.0 for v in vec]
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

external_llm = ExternalLLMProvider()