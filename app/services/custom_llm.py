"""Custom OpenAI-совместимый LLM (per-user endpoint)."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


class CustomLLMProvider:
    name = "custom_llm"

    def __init__(self, base_url: str, api_key: str, model: str | None = None) -> None:
        if not base_url:
            raise RuntimeError("custom_llm: base_url обязателен")
        if not api_key:
            raise RuntimeError("custom_llm: api_key обязателен")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = (model or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self, prompt: str, system: str | None = None,
        max_tokens: int = 15000, temperature: float = 0.7,
        job_id: str | None = None, api_key: str | None = None,
    ) -> str:
        print(f"[custom_llm] trying model={self._model}")
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model, "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature), "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"custom_llm timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"custom_llm network: {exc}") from exc
        if resp.status_code in (401, 403):
            raise RuntimeError(f"custom_llm: неверный ключ ({resp.status_code})")
        if resp.status_code == 429:
            raise RuntimeError("custom_llm: 429 rate limit")
        if resp.status_code >= 500:
            raise RuntimeError(f"custom_llm: server error {resp.status_code}")
        if resp.status_code != 200:
            raise RuntimeError(f"custom_llm HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"custom_llm bad JSON: {exc}") from exc
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
