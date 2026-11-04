"""Gemini TTS для PTT: короткие фразы, серверный кэш MP3."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import subprocess
from pathlib import Path

import httpx

from config import GEMINI_API_KEY, TTS_DIR

_MODELS = ("gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts")
_VOICE = "Ludo"
_MAX_CHARS = 1200
_LOCK = asyncio.Lock()


class TTSError(RuntimeError):
    pass


def cache_key(text: str) -> str:
    return hashlib.sha256(f"{_VOICE}|{text}".encode("utf-8")).hexdigest()


def cache_file(text: str) -> Path:
    return TTS_DIR / f"{cache_key(text)}.mp3"


def _cache_path(text: str) -> Path:
    return cache_file(text)


def _to_mp3(wav: bytes) -> bytes:
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0", "-vn", "-codec:a", "libmp3lame",
                "-b:a", "48k", "-f", "mp3", "pipe:1",
            ],
            input=wav,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"ffmpeg: {exc}") from exc


async def _call_model(model: str, text: str) -> bytes:
    if not GEMINI_API_KEY:
        raise TTSError("GEMINI_API_KEY не задан")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": _VOICE}}
            },
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": GEMINI_API_KEY},
            json=payload,
        )
    if resp.status_code == 429:
        raise TTSError("429")
    if resp.status_code >= 400:
        raise TTSError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"bad TTS response: {exc}") from exc
    raise TTSError("no audio in TTS response")


async def synthesize_ex(text: str) -> tuple[bytes, bool, str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        raise TTSError("empty text")
    if len(clean) > _MAX_CHARS:
        clean = clean[:_MAX_CHARS].rsplit(" ", 1)[0].strip() + "…"
    path = _cache_path(clean)
    if path.is_file():
        return path.read_bytes(), True, "cache"

    async with _LOCK:
        if path.is_file():
            return path.read_bytes(), True, "cache"
        last_error: Exception | None = None
        for model in _MODELS:
            try:
                wav = await _call_model(model, clean)
                mp3 = await asyncio.to_thread(_to_mp3, wav)
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(mp3)
                tmp.replace(path)
                return mp3, False, model
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise TTSError(str(last_error)[:300])


async def synthesize(text: str) -> bytes:
    return (await synthesize_ex(text))[0]
