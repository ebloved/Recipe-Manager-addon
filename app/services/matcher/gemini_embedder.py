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

import logging
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

# Генерация рецепта (max_tokens=2500) занимает 15–60 с; 30-секундный
# таймаут эмбеддингов для complete() мал. Отдельная константа, чтобы
# не влиять на embed()/health.
_GENERATE_TIMEOUT = httpx.Timeout(120.0, connect=15.0)

# Per-model budget и общий deadline для complete(). Async-job снимает
# ограничение nginx, но бесконечно висеть тоже нельзя. 3 модели × 90с
# с общим лимитом 240с: если первая отвалилась быстро (503 за 8с),
# у оставшихся много запаса; если timeout — режем и пробуем следующую.
_PER_MODEL_TIMEOUT = 90.0
_TOTAL_DEADLINE = 240.0


logger = logging.getLogger(__name__)


class GeminiProvider(EmbeddingProvider, GenerativeProvider):
    """Провайдер Gemini: эмбеддинги + chat."""

    name = "gemini"
    model = _GENERATIVE_FALLBACK_MODEL
    model_key = f"gemini:{_EMBEDDING_MODEL}:{_EMBEDDING_DIM}"

    # Gemini embedding-001 даёт высокое «фоновое» сходство между
    # семантически далёкими текстами: 0.6–0.85 для случайных пар.
    # Это уводит даже мусорных кандидатов выше порога suggest (0.80).
    #
    # Значение 0.75 эмпирически отсекает шум, но оставляет рабочий
    # диапазон для реальных совпадений. Каскад нормализует score:
    #   adjusted = (raw - baseline) / (1 - baseline)
    # Например: 0.85 → 0.40, 0.90 → 0.60, 0.95 → 0.80, 0.99 → 0.96.
    baseline_similarity = 0.75

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
        """Cascade по GEMINI_MODELS с per-model timeout и общим дедлайном.

        Timeout / 404 / 429 / 5xx — retriable (пробуем следующую модель).
        Auth / network / bad request — fatal (пробрасываем наверх).
        """
        if not GEMINI_API_KEY:
            raise ProviderUnavailable("GEMINI_API_KEY не задан")

        models = list(GEMINI_MODELS) or [self.model]
        self._last_usage = {
            "models_tried": [],
            "attempts": [],
            "prompt_chars": len(prompt or ""),
        }
        errors: list[str] = []
        start = asyncio.get_event_loop().time()

        print(
            f"[gemini] start: prompt={len(prompt or '')}chars, "
            f"max_tokens={max_tokens}, models={models}, "
            f"per_model={_PER_MODEL_TIMEOUT:.0f}s, deadline={_TOTAL_DEADLINE:.0f}s"
        )

        for model in models:
            elapsed_total = asyncio.get_event_loop().time() - start
            remaining = _TOTAL_DEADLINE - elapsed_total
            if remaining < 10.0:
                self._last_usage["attempts"].append({
                    "model": model, "status": "skipped",
                    "reason": f"deadline (remaining {remaining:.0f}s)",
                })
                errors.append(f"{model}: skipped (deadline)")
                logger.warning(
                    "[gemini] %s skipped: only %.0fs left", model, remaining)
                continue

            budget = min(_PER_MODEL_TIMEOUT, remaining)
            self._last_usage["models_tried"].append(model)
            t0 = asyncio.get_event_loop().time()
            print(f"[gemini] try {model} (budget {budget:.0f}s, "
                  f"total_remaining {remaining:.0f}s)")

            try:
                result = await asyncio.wait_for(
                    self._complete_one(
                        model, prompt, system, max_tokens, temperature),
                    timeout=budget,
                )
                elapsed = asyncio.get_event_loop().time() - t0
                self._last_usage["attempts"].append({
                    "model": model, "status": "ok",
                    "elapsed_s": round(elapsed, 2),
                })
                print(f"[gemini] {model} ok in {elapsed:.1f}s")
                return result

            except (asyncio.TimeoutError, TimeoutError):
                elapsed = asyncio.get_event_loop().time() - t0
                self._last_usage["attempts"].append({
                    "model": model, "status": "timeout",
                    "elapsed_s": round(elapsed, 2),
                })
                errors.append(f"{model}: timeout at {elapsed:.0f}s")
                logger.warning(
                    "[gemini] %s TIMEOUT at %.1fs — try next model",
                    model, elapsed)
                continue

            except Exception as exc:  # noqa: BLE001
                elapsed = asyncio.get_event_loop().time() - t0
                msg = str(exc) or type(exc).__name__
                retriable = self._is_retriable(msg)
                self._last_usage["attempts"].append({
                    "model": model, "status": "error",
                    "elapsed_s": round(elapsed, 2),
                    "error": msg[:200], "retriable": retriable,
                })
                logger.warning(
                    "[gemini] %s failed in %.1fs: %s (%s)",
                    model, elapsed, msg,
                    "retriable" if retriable else "FATAL")
                if retriable:
                    errors.append(f"{model}: {msg}")
                    continue
                raise

        total_elapsed = asyncio.get_event_loop().time() - start
        logger.error(
            "[gemini] ALL models failed in %.0fs: %s",
            total_elapsed, "; ".join(errors))

        if errors and all("timeout" in e for e in errors):
            raise ProviderUnavailable(
                f"Все {len(models)} модели Gemini не ответили за "
                f"{_PER_MODEL_TIMEOUT:.0f}s каждая (итого {total_elapsed:.0f}s). "
                f"Промпт {len(prompt or '')} символов, max_tokens={max_tokens}. "
                f"Попробуйте уменьшить samples или повторите через минуту."
            )
        if errors and all(
            ("503" in e or "server error" in e) for e in errors
        ):
            raise ProviderUnavailable(
                f"Gemini перегружен (503) — все {len(models)} модели вернули "
                f"server error за {total_elapsed:.0f}s. Попробуйте через 1–2 минуты."
            )
        raise ProviderUnavailable(
            f"All {len(models)} models failed ({total_elapsed:.0f}s): "
            + "; ".join(errors)
        )

    @staticmethod
    def _is_retriable(msg: str) -> bool:
        m = msg.lower()
        return any(k in m for k in (
            "server error", "http 404", "http 429",
            "http 500", "http 502", "http 503",
            "timeout",
        ))

    async def _complete_one(
        self, model: str,
        prompt: str, system: str | None,
        max_tokens: int, temperature: float,
    ) -> str:
        """Отправляет запрос в generateContent и возвращает текст ответа."""
        url = f"{_API_BASE}/models/{model}:generateContent"
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
            "x-goog-api-key": GEMINI_API_KEY,
        }

        client_kwargs: dict = {"timeout": _GENERATE_TIMEOUT}
        if GEMINI_PROXY:
            client_kwargs["proxy"] = GEMINI_PROXY

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
            self._last_usage.update({
                "finish_reason": candidates[0].get("finishReason"),
                "usage": data.get("usageMetadata") or {},
            })
        except (KeyError, IndexError, TypeError):
            # Иногда Gemini возвращает пустой ответ из-за safety-фильтра
            self._last_usage.update({
                "finish_reason": None,
                "usage": data.get("usageMetadata") or {},
            })
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