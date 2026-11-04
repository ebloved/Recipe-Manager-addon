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
import json
import asyncio
import math
from datetime import datetime, timezone

import httpx

from stores.settings import settings_store
from config import (
    GEMINI_API_KEY,
    GEMINI_MODELS,
    GENERATOR_MAX_TOKENS,
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

# Background Execution через Interactions API: создаём interaction
# с background=true, затем опрашиваем статус. Модель может думать
# сколько угодно — жёсткого таймаута на «размышления» нет.
_POLL_INTERVAL = 5.0          # секунд между опросами
_MAX_POLL_DURATION = 300.0    # 10 минут на одну модель (safety)


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
        key = api_key or GEMINI_API_KEY
        if not key:
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
            "x-goog-api-key": GEMINI_API_KEY,
        }

        client_kwargs: dict = {"timeout": _TIMEOUT}
        if GEMINI_PROXY:
            client_kwargs["proxy"] = GEMINI_PROXY

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
        max_tokens: int = GENERATOR_MAX_TOKENS,
        temperature: float = 0.7,
        job_id: str | None = None,
        api_key: str | None = None,
    ) -> str:
        """Background Execution через Interactions API с polling.

        Для каждой модели из GEMINI_MODELS:
          1. POST /v1beta/interactions  { background: true }
          2. GET  /v1beta/interactions/{id}  пока status == in_progress
          3. completed → вернуть output_text
          4. failed (503/429/5xx) → следующая модель

        Никаких жёстких таймаутов на «размышления» модели.
        """
        key = api_key or GEMINI_API_KEY
        if not key:
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
            f"[gemini] start (background): prompt={len(prompt or '')}chars, "
            f"max_tokens={max_tokens}, models={models}"
        )

        for model in models:
            self._last_usage["models_tried"].append(model)
            t0 = asyncio.get_event_loop().time()
            print(f"[gemini] try {model} (background, poll every {_POLL_INTERVAL:.0f}s)")

            try:
                # 1. Создаём фоновую интеракцию
                interaction_id = await self._start_background_interaction(
                    model, prompt, system, max_tokens, temperature, key
                )
                if job_id:
                    from stores.jobs import jobs_store
                    await jobs_store.update(job_id, interaction_id=interaction_id, model=model)
                print(f"[gemini] {model} interaction_id={interaction_id}")

                # 2. Опрашиваем до терминального статуса
                output_text, status, final_error = await self._poll_interaction(
                    interaction_id, model, key
                )
                elapsed = asyncio.get_event_loop().time() - t0

                if status == "completed":
                    self._last_usage["attempts"].append({
                        "model": model, "status": "ok",
                        "elapsed_s": round(elapsed, 2),
                    })
                    print(f"[gemini] {model} completed in {elapsed:.1f}s")
                    return output_text

                # status == "failed" или "cancelled"
                msg = final_error or f"status={status}"
                retriable = (
                    self._is_retriable(msg)
                    or status in ("incomplete", "cancelled", "requires_action")
                    or not msg
                    or msg == "{}"
                    or "empty error" in msg.lower()
                )
                self._last_usage["attempts"].append({
                    "model": model, "status": "error",
                    "elapsed_s": round(elapsed, 2),
                    "error": msg[:200], "retriable": retriable,
                })
                print(f"[gemini] {model} failed in {elapsed:.1f}s: {msg} "
                      f"({'retriable' if retriable else 'FATAL'})")
                if retriable:
                    errors.append(f"{model}: {msg}")
                    continue
                raise ProviderUnavailable(msg)

            except Exception as exc:  # noqa: BLE001
                elapsed = asyncio.get_event_loop().time() - t0
                msg = str(exc) or type(exc).__name__
                retriable = self._is_retriable(msg)
                self._last_usage["attempts"].append({
                    "model": model, "status": "error",
                    "elapsed_s": round(elapsed, 2),
                    "error": msg[:200], "retriable": retriable,
                })
                print(f"[gemini] {model} failed in {elapsed:.1f}s: {msg} "
                      f"({'retriable' if retriable else 'FATAL'})")
                if retriable:
                    errors.append(f"{model}: {msg}")
                    continue
                raise

        total_elapsed = asyncio.get_event_loop().time() - start
        print(f"[gemini] ALL models failed in {total_elapsed:.0f}s: {'; '.join(errors)}")

        if errors and all(
            ("503" in e or "server error" in e or "rate" in e.lower())
            for e in errors
        ):
            raise ProviderUnavailable(
                f"Gemini перегружен (503/rate limit) — все {len(models)} модели "
                f"вернули ошибку за {total_elapsed:.0f}s. Попробуйте через 1–2 минуты."
            )
        raise ProviderUnavailable(
            f"All {len(models)} models failed ({total_elapsed:.0f}s): "
            + "; ".join(errors)
        )

    async def _start_background_interaction(
        self, model: str, prompt: str, system: str | None,
        max_tokens: int, temperature: float, api_key: str | None = None
    ) -> str:
        """POST /v1beta/interactions → interaction_id."""
        url = "https://generativelanguage.googleapis.com/v1beta/interactions"
        body: dict = {
            "model": model,
            "input": prompt,
            "background": True,
        }
        if system:
            body["system_instruction"] = system
        gen_config: dict = {
            "max_output_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        body["generation_config"] = gen_config

        headers = {
            "x-goog-api-key": api_key or GEMINI_API_KEY,
            "Content-Type": "application/json",
            "Api-Revision": "2026-05-20",
        }
        client_kwargs: dict = {"timeout": 30.0}
        if GEMINI_PROXY:
            client_kwargs["proxy"] = GEMINI_PROXY

        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code != 200:
            msg = f"HTTP {resp.status_code} — {resp.text[:200]}"
            if resp.status_code in (401, 403):
                raise ProviderUnavailable(f"Gemini auth: {msg}")
            if resp.status_code == 429:
                raise RateLimited("Gemini: 429 Too Many Requests")
            raise ProviderUnavailable(f"Gemini create interaction: {msg}")

        data = resp.json()
        interaction_id = data.get("id")
        if not interaction_id:
            raise ProviderUnavailable(f"No interaction id in response: {data}")
        return interaction_id

    async def _poll_interaction(
        self, interaction_id: str, model: str, api_key: str | None = None
    ) -> tuple[str, str, str | None]:
        """GET /v1beta/interactions/{id} → (output_text, status, error)."""
        url = f"https://generativelanguage.googleapis.com/v1beta/interactions/{interaction_id}"
        headers = {
            "x-goog-api-key": api_key or GEMINI_API_KEY,
            "Api-Revision": "2026-05-20",
        }
        client_kwargs: dict = {"timeout": 15.0}
        if GEMINI_PROXY:
            client_kwargs["proxy"] = GEMINI_PROXY

        t_start = asyncio.get_event_loop().time()
        last_status = None
        poll_n = 0

        async with httpx.AsyncClient(**client_kwargs) as client:
            while True:
                elapsed = asyncio.get_event_loop().time() - t_start
                if elapsed > float(settings_store.get("gemini_poll_duration", 300.0)):
                    raise ProviderUnavailable(
                        f"{model}: poll timeout after {elapsed:.0f}s "
                        f"(status={last_status})"
                    )

                try:
                    resp = await client.get(url, headers=headers)
                except httpx.RequestError as exc:
                    # сеть моргнула — пробуем ещё
                    print(f"[gemini] {model} poll network error: {exc}")
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                if resp.status_code != 200:
                    msg = f"poll HTTP {resp.status_code} — {resp.text[:200]}"
                    if resp.status_code in (401, 403):
                        raise ProviderUnavailable(f"Gemini poll auth: {msg}")
                    if resp.status_code == 404:
                        raise ProviderUnavailable(f"{model}: interaction lost: {msg}")
                    if resp.status_code == 429:
                        await asyncio.sleep(_POLL_INTERVAL * 2)
                        continue
                    raise ProviderUnavailable(f"Gemini poll: {msg}")

                data = resp.json()
                status = data.get("status")
                poll_n += 1

                if status != last_status:
                    print(f"[gemini] {model} poll #{poll_n}: status={status} "
                          f"({elapsed:.0f}s)")
                    last_status = status
                elif poll_n % 6 == 0:
                    # раз в ~30s напоминаем, что живы
                    print(f"[gemini] {model} still {status} ({elapsed:.0f}s)")

                if status == "completed":
                    # Новый формат: текст в steps[] → type=model_output → content[] → text
                    out = ""
                    steps = data.get("steps") or []
                    for step in steps:
                        if step.get("type") == "model_output":
                            for item in (step.get("content") or []):
                                if item.get("type") == "text":
                                    out += item.get("text", "")

                    # Fallback на старый формат (output_text / outputs)
                    if not out:
                        out = data.get("output_text") or ""
                    if not out:
                        outputs = data.get("outputs") or []
                        if outputs:
                            last = outputs[-1]
                            if isinstance(last, dict):
                                out = last.get("text", "")

                    out = out.strip()
                    if not out:
                        print(f"[gemini] {model} completed but text is empty! keys={list(data.keys())}")
                    return out, "completed", None

                if status in ("failed", "cancelled", "requires_action", "incomplete"):
                    err = data.get("error") or {}
                    if isinstance(err, dict):
                        err_msg = err.get("message") or str(err) or ""
                    else:
                        err_msg = str(err) or ""

                    # Диагностика: пустой error ({}) — логируем полный ответ
                    if not err_msg or err_msg == "{}":
                        print(
                            f"[gemini] {model} status={status} empty error. "
                            f"Full response: {json.dumps(data, ensure_ascii=False)[:1000]}"
                        )
                        err_msg = f"status={status} (empty error, likely transient)"

                    # Для incomplete — покажем сколько текста успело прийти
                    if status == "incomplete":
                        partial_len = 0
                        for step in (data.get("steps") or []):
                            if step.get("type") == "model_output":
                                for item in (step.get("content") or []):
                                    if item.get("type") == "text":
                                        partial_len += len(item.get("text", ""))
                        err_msg = f"incomplete (partial {partial_len} chars): {err_msg}"

                    return "", status, err_msg

                await asyncio.sleep(_POLL_INTERVAL)

    @staticmethod
    def _is_retriable(msg: str) -> bool:
        m = msg.lower()
        return any(k in m for k in (
            "server error", "http 404", "http 429",
            "http 500", "http 502", "http 503",
            "timeout", "rate limit", "rate_limit",
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

        if not GEMINI_API_KEY:
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
            "x-goog-api-key": GEMINI_API_KEY,
        }

        client_kwargs: dict = {"timeout": httpx.Timeout(10.0)}
        if GEMINI_PROXY:
            client_kwargs["proxy"] = GEMINI_PROXY

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
                notes=f"embed={_EMBEDDING_MODEL}, chat={self.model}",
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