"""Чистые утилиты без I/O и внешних зависимостей."""
from __future__ import annotations

import re
from typing import Any


def extract_video_id(url: str) -> str | None:
    for pat in (
        r"shorts/([a-zA-Z0-9_-]{11})",
        r"watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"embed/([a-zA-Z0-9_-]{11})",
    ):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def clean_srt_text(raw: str) -> str:
    raw = re.sub(r"^WEBVTT.*?\n\n", "", raw, flags=re.DOTALL)
    raw = re.sub(r"\d+\n\d{2}:\d{2}:\d{2}[.,]\d{3} --> .*?\n", "", raw)
    raw = re.sub(r"\d{2}:\d{2}:\d{2}[.,]\d{3} --> .*?\n", "", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = re.sub(r"^[a-z-]+:.*$", "", raw, flags=re.MULTILINE)

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    cleaned: list[str] = []
    for line in lines:
        if not cleaned:
            cleaned.append(line)
            continue
        prev = cleaned[-1]
        if line == prev or line in prev:
            continue
        if prev in line:
            cleaned[-1] = line
            continue
        cleaned.append(line)
    return " ".join(cleaned)


def safe_call(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def first_or_str(v: Any) -> str | None:
    if not v:
        return None
    if isinstance(v, list):
        return str(v[0]).strip() if v else None
    return str(v).strip()


def to_int_minutes(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def extract_servings_count(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d+", str(text))
    return int(m.group()) if m else None