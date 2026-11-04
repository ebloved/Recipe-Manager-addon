"""OrcaRouter — OpenAI-совместимый роутер (только user-ключи).

Fallback внутри Orca:
  1. tencent/hy4-preview-free
  2. deepseek/deepseek-v4.1-flash-free
  3. deepseek/deepseek-v4-flash-free
  4. orca/orcaverify-text1.0-free

Поведение по кодам:
  401, 403 invalid_key / unauthorized → abort
  403 model_access_denied             → skip модели
  429, 499                            → skip модели
  5xx, timeout, network, bad JSON     → skip модели
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import ORC_BASE_URL, ORC_MODEL, ORC_MODELS, ORC_TIMEOUT

logger = logging.getLogger(__name__)

_MODEL_TIMEOUTS: dict[str, float] = {
    "tencent/hy4-preview-free": 60.0,
    "deepseek/deepseek-v4.1-flash-free": 45.0,
    "deepseek/deepseek-v4-flash-free": 45.0,
    "orca/orcaverify-text1.0-free": 30.0,
}


class _OrcaAuthError(RuntimeError):
    """401 / 403 invalid key."""


class _OrcaSkip(RuntimeError):
    """429 / 499 / 403 model_access_denied."""


class _OrcaRetry(RuntimeError):
    """5xx / timeout / bad JSON."""


def _is_auth_failure(status_code: int, body: str) -> bool:
    if status_code == 401:
        return True
    if status_code != 403:
        return False
    low = (body or "").lower()
    if "model_access_denied" in low:
        return False
    if "does not have access to model" in low:
        return False
    return True


class OrcaRouterProvider:
    name = "orcarouter"

    def __init__(self) -> None:
        self._models = list(ORC_MODELS) if ORC_MODELS else [ORC_MODEL]
        self._last_usage: dict[str, Any] = {}

    async def complete(
        self, prompt: str, system: str | None = None,
        max_tokens: int = 15000, temperature: float = 0.7,
        job_id: str | None = None, api_key: str | None = None,
    ) -> str:
        if not api_key:
            raise RuntimeError("OrcaRouter: api_key обязателен")

        errors: list[str] = []
        tried: list[str] = []

        for model in self._models:
            tried.append(model)
            timeout = _MODEL_TIMEOUTS.get(model, ORC_TIMEOUT)
            try:
                print(f"[orca] trying model={model} (timeout={timeout:.0f}s)")
                text = await self._complete_one(
                    model, prompt, system, max_tokens, temperature, api_key, timeout,
                )
                if not text:
                    raise _OrcaRetry("empty response")
                self._last_usage = {"model": model, "models_tried": tried}
                print(f"[orca] ✓ model={model} ok")
                return text
            except _OrcaAuthError:
                raise
            except _OrcaSkip as exc:
                logger.warning("[orca] %s skip: %s", model, exc)
                errors.append(f"{model}: {exc}")
                continue
            except _OrcaRetry as exc:
                logger.warning("[orca] %s fail: %s", model, exc)
                errors.append(f"{model}: {exc}")
                continue
            except Exception as exc:
                logger.warning("[orca] %s unexpected: %s", model, exc)
                errors.append(f"{model}: {exc}")
                continue

        raise RuntimeError("All Orca models failed: " + "; ".join(errors))

    async def _complete_one(
        self, model: str, prompt: str, system: str | None,
        max_tokens: int, temperature: float, api_key: str, timeout: float,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        url = f"{ORC_BASE_URL}/chat/completions"
        payload = {
            "model": model, "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature), "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise _OrcaRetry(f"timeout {timeout:.0f}s: {exc}") from exc
        except httpx.RequestError as exc:
            raise _OrcaRetry(f"network: {exc}") from exc

        body = resp.text or ""

        if resp.status_code in (401, 403):
            if _is_auth_failure(resp.status_code, body):
                raise _OrcaAuthError(f"auth failed ({resp.status_code}): {body[:200]}")
            raise _OrcaSkip(f"403 no access to model: {body[:150]}")

        if resp.status_code == 429:
            raise _OrcaSkip(f"429 rate limit: {body[:150]}")
        if resp.status_code == 499:
            raise _OrcaSkip("499 blocked")
        if resp.status_code >= 500:
            raise _OrcaRetry(f"server error {resp.status_code}")
        if resp.status_code != 200:
            raise _OrcaRetry(f"HTTP {resp.status_code}: {body[:200]}")

        try:
            data = resp.json()
        except Exception as exc:
            raise _OrcaRetry(f"bad JSON: {exc}") from exc

        choices = data.get("choices") or []
        if not choices:
            return ""
        content = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text") or "")
                elif isinstance(b, str):
                    parts.append(b)
            content = "".join(parts)
        return str(content).strip()


orcarouter = OrcaRouterProvider()
