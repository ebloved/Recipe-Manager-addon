"""YouTube Shorts → рецепт."""
from __future__ import annotations

import uuid

import aiofiles
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from config import DOWNLOAD_DIR
from helpers import clean_srt_text, extract_video_id
from services.gemini import call_gemini
from services.ytdlp import run_ytdlp

router = APIRouter(tags=["youtube"])


@router.post("/api/download")
async def api_download(url: str = Form(...)):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(400, "Не удалось извлечь ID видео из URL")
    job_id = uuid.uuid4().hex[:8]
    result = await run_ytdlp(url, job_id)
    if result["returncode"] != 0 and not result["files"]:
        return JSONResponse(
            status_code=502,
            content={
                "error": "yt-dlp завершился с ошибкой",
                "job_id": job_id,
                "stderr": result["stderr"][-3000:],
            },
        )
    return {
        "status": "ok",
        "video_id": video_id,
        "job_id": job_id,
        "files": result["files"],
        "count": len(result["files"]),
    }


@router.post("/api/generate-recipe")
async def generate_recipe(job_id: str = Form(...)):
    files = sorted(
        list(DOWNLOAD_DIR.glob(f"{job_id}_*.srt"))
        + list(DOWNLOAD_DIR.glob(f"{job_id}_*.vtt"))
    )
    if not files:
        raise HTTPException(404, detail={"error": "Субтитры не найдены", "job_id": job_id})

    combined_text = ""
    for f in files:
        async with aiofiles.open(f, "r", encoding="utf-8") as fh:
            combined_text += clean_srt_text(await fh.read()) + "\n\n"
    if not combined_text.strip():
        raise HTTPException(400, "Не удалось извлечь текст из субтитров")

    markdown, used_model = await call_gemini(combined_text)
    out_file = DOWNLOAD_DIR / f"{job_id}_recipe.md"
    async with aiofiles.open(out_file, "w", encoding="utf-8") as fh:
        await fh.write(markdown)

    return {
        "status": "ok",
        "job_id": job_id,
        "model": used_model,
        "markdown": markdown,
        "file": out_file.name,
        "download_url": f"files/{out_file.name}",
    }