"""YouTube Shorts → рецепт.

Пайплайн:
  1. POST /api/download         — yt-dlp скачивает субтитры в /downloads
  2. POST /api/generate-recipe  — Gemini превращает субтитры в Markdown
  3. Сохранение готового .md    — можно скачать, либо сразу постить
                                   в /api/recipes (там linker подхватит
                                   product-блоки, если они есть в шаблоне)

Изменения относительно предыдущей версии:
  - В `/api/generate-recipe` добавлена возможность сразу сохранить рецепт
    (флаг `save`), с прогоном через linker.
  - В `/api/download` добавлено логирование stderr yt-dlp — чтобы при
    ошибках было видно причину, а не просто rc=1.
"""
from __future__ import annotations

import logging
import re
import uuid

import aiofiles
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from config import DOWNLOAD_DIR
from helpers import clean_srt_text, extract_video_id
from recipe_manager.importer import parse_markdown_recipe
from services.gemini import call_gemini
from services.linker import link_recipe_ingredients
from services.ytdlp import run_ytdlp
from stores import recipe_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["youtube"])


# ---------------------------------------------------------------------------
# 1. Скачивание субтитров
# ---------------------------------------------------------------------------

@router.post("/api/download")
async def api_download(url: str = Form(...)):
    """Скачивает субтитры YouTube через yt-dlp.

    Возвращает job_id, который затем используется в /api/generate-recipe.
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(400, "Не удалось извлечь ID видео из URL")

    job_id = uuid.uuid4().hex[:8]
    result = await run_ytdlp(url, job_id)

    if result["returncode"] != 0 and not result["files"]:
        # Логируем stderr целиком — пригодится для диагностики
        stderr_tail = result["stderr"][-4000:] if result["stderr"] else ""
        logger.warning(
            "yt-dlp job=%s rc=%s, stderr:\n%s",
            job_id, result["returncode"], stderr_tail,
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "yt-dlp завершился с ошибкой",
                "job_id": job_id,
                "stderr": stderr_tail[-3000:],
            },
        )

    return {
        "status": "ok",
        "video_id": video_id,
        "job_id": job_id,
        "files": result["files"],
        "count": len(result["files"]),
    }


# ---------------------------------------------------------------------------
# 2. Генерация рецепта через Gemini
# ---------------------------------------------------------------------------

@router.post("/api/generate-recipe")
async def generate_recipe(
    job_id: str = Form(...),
    save: bool = Form(False),
    link: bool = Form(True),
):
    """Генерирует Markdown-рецепт по субтитрам.

    Параметры:
        job_id  — идентификатор, полученный от /api/download
        save    — если True, рецепт сразу сохраняется в базу
        link    — если True (по умолчанию) и save=True, прогоняется
                  через linker для связки product-блоков

    Возвращает:
        {
            "status": "ok",
            "job_id": "...",
            "model": "gemini-...",
            "markdown": "...",
            "file": "...",
            "download_url": "...",
            "recipe": {...}  # только если save=True
        }
    """
    # Ищем файлы субтитров
    files = sorted(
        list(DOWNLOAD_DIR.glob(f"{job_id}_*.srt"))
        + list(DOWNLOAD_DIR.glob(f"{job_id}_*.vtt"))
    )
    if not files:
        raise HTTPException(
            404,
            detail={"error": "Субтитры не найдены", "job_id": job_id},
        )

    # Склеиваем текст
    combined_text = ""
    for f in files:
        async with aiofiles.open(f, "r", encoding="utf-8") as fh:
            combined_text += clean_srt_text(await fh.read()) + "\n\n"

    if not combined_text.strip():
        raise HTTPException(400, "Не удалось извлечь текст из субтитров")

    # Генерируем через Gemini
    markdown, used_model = await call_gemini(combined_text)

    # Сохраняем .md файл на диск (в /downloads)
    out_file = DOWNLOAD_DIR / f"{job_id}_recipe.md"
    async with aiofiles.open(out_file, "w", encoding="utf-8") as fh:
        await fh.write(markdown)

    result: dict = {
        "status": "ok",
        "job_id": job_id,
        "model": used_model,
        "markdown": markdown,
        "file": out_file.name,
        "download_url": f"files/{out_file.name}",
    }

    # --- Опциональное сохранение в базу ---
    if save:
        try:
            parsed = parse_markdown_recipe(markdown)
        except ValueError as exc:
            # Не падаем — просто возвращаем рецепт без сохранения
            logger.warning("Не удалось распарсить MD от Gemini: %s", exc)
            result["save_error"] = f"markdown_parse_failed: {exc}"
            return result

        if link:
            try:
                parsed = await link_recipe_ingredients(parsed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Linker упал при save из YouTube: %s", exc)

        parsed.pop("_linker_stats", None)

        try:
            recipe = await recipe_store.add(parsed)
            result["recipe"] = recipe
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось сохранить рецепт из YouTube: %s", exc)
            result["save_error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# 3. Просмотр/удаление скачанных файлов (диагностика)
# ---------------------------------------------------------------------------

@router.get("/api/youtube/jobs")
async def list_jobs():
    """Список недавних job-ов (по файлам в /downloads).

    Полезно для отладки: если yt-dlp ругается, но файлов нет —
    значит скачивание упало до записи.
    """
    files = sorted(
        DOWNLOAD_DIR.glob("*_recipe.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files[:50]:  # последние 50
        # job_id — первые 8 символов до первого подчёркивания
        name = f.name
        m = re.match(r"^([a-f0-9]{8})_", name)
        job_id = m.group(1) if m else None

        srt_files = sorted(DOWNLOAD_DIR.glob(f"{job_id}_*.srt")) if job_id else []
        vtt_files = sorted(DOWNLOAD_DIR.glob(f"{job_id}_*.vtt")) if job_id else []

        result.append({
            "job_id": job_id,
            "md_file": name,
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime,
            "subtitles": [p.name for p in (srt_files + vtt_files)],
        })
    return {"jobs": result, "count": len(result)}