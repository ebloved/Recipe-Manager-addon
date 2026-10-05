"""Обёртка над yt-dlp (скачивание субтитров)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from config import COOKIES_FILE, DOWNLOAD_DIR, SUB_LANGS


async def run_ytdlp(url: str, job_id: str) -> dict:
    outtmpl = str(DOWNLOAD_DIR / f"{job_id}_%(title)s.%(ext)s")
    cmd = [
        "yt-dlp", "--skip-download",
        "--js-runtimes", "node",
        "--write-auto-subs", "--write-subs",
        "--sub-langs", SUB_LANGS,
        "--sub-format", "vtt/srt/best",
        "--convert-subs", "srt",
        "--no-playlist",
        "--sleep-requests", "1",
        "--sleep-subtitles", "5",
        "--extractor-retries", "5",
        "--retry-sleep", "429:60",
        "--output", outtmpl,
    ]
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        cmd += ["--cookies", COOKIES_FILE]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode(errors="replace")
    print(f"[yt-dlp job={job_id}] rc={proc.returncode}")
    print(f"[yt-dlp job={job_id}] stderr:\n{stderr_text}")

    files = sorted(DOWNLOAD_DIR.glob(f"{job_id}_*"))
    return {
        "job_id": job_id,
        "returncode": proc.returncode,
        "stderr": stderr_text,
        "files": [
            {
                "filename": f.name,
                "size": f.stat().st_size,
                "download_url": f"files/{f.name}",
            }
            for f in files
        ],
    }