"""YouTube → рецепт.

Источник транскриптов — Apify (Actor `APIFY_ACTOR_ID`).
yt-dlp больше не используется.

Пайплайн:
  1. POST /api/download         — Apify отдаёт текст транскрипта (с кэшем)
  2. POST /api/generate-recipe  — LLM превращает текст в Markdown
  3. Сохранение готового .md    — можно скачать, либо сразу постить
                                   в /api/recipes (linker подхватит
                                   product-блоки, если они есть)

Служебное:
  GET /api/youtube/status  — включён ли импорт + квота Apify (для всех)
  GET /api/youtube/limits  — подробный статус Apify (только админ)
"""
from __future__ import annotations

import logging
import re
import uuid

import aiofiles
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from config import DOWNLOAD_DIR, FEATURE_YOUTUBE_IMPORT
from helpers import clean_srt_text, extract_video_id
from recipe_manager.importer import parse_markdown_recipe
from services.apify_transcript import (
    ApifyError,
    fetch_transcript,
    get_usage,
    reset_usage_cache,
)
from services.gemini import call_gemini
from services.linker import link_recipe_ingredients
from stores import recipe_store
from stores.youtube_transcripts import youtube_transcripts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["youtube"])


def _require_enabled() -> None:
    if not FEATURE_YOUTUBE_IMPORT:
        raise HTTPException(
            503,
            "YouTube-импорт отключён. Включите опцию youtube_import_enabled "
            "(FEATURE_YOUTUBE_IMPORT=true) и перезапустите приложение.",
        )


def _require_admin(request: Request) -> None:
    from services.auth import get_current_user

    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Только администратор может смотреть лимиты Apify")


async def _quota_or_503() -> dict:
    """Проверяет лимит Apify; 503, если кредиты на исходе."""
    usage = await get_usage()
    if usage.get("blocked"):
        if usage.get("reason") == "token_missing":
            detail = (
                "Импорт временно недоступен: Apify не настроен (нет APIFY_TOKEN). "
                "Обратитесь к администратору."
            )
        else:
            detail = (
                "Импорт временно недоступен: лимит транскрипций исчерпан. "
                "Попробуйте позже."
            )
        raise HTTPException(503, detail)
    return usage


@router.get("/api/youtube/status")
async def youtube_status():
    """Состояние фичи и квоты — фронтенд скрывает кнопки при лимите."""
    usage = await get_usage()
    return {
        "enabled": FEATURE_YOUTUBE_IMPORT,
        "quota": usage,
    }


@router.get("/api/youtube/limits")
async def youtube_limits(request: Request, refresh: int = 0):
    """Подробный статус Apify для админки. `?refresh=1` — сбросить кэш."""
    _require_admin(request)
    if refresh:
        reset_usage_cache()
    return await get_usage(force=bool(refresh))


# ---------------------------------------------------------------------------
# 1. Получение транскрипта через Apify
# ---------------------------------------------------------------------------

@router.post("/api/download")
async def api_download(url: str = Form(...)):
    """Забирает транскрипт YouTube через Apify.

    Возвращает job_id для /api/generate-recipe.
    """
    _require_enabled()
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(400, "Не удалось извлечь ID видео из URL")

    await _quota_or_503()

    job_id = uuid.uuid4().hex[:8]
    try:
        transcript = await fetch_transcript(url, video_id)
    except ApifyError as exc:
        logger.warning("Apify: video=%s: %s", video_id, exc.message)
        return JSONResponse(
            status_code=502,
            content={
                "error": exc.message,
                "job_id": job_id,
                "video_id": video_id,
            },
        )

    text = transcript["text"]
    # Пишем .txt в /downloads: /api/generate-recipe читает его так же,
    # как раньше читал .srt/.vtt.
    out_file = DOWNLOAD_DIR / f"{job_id}_{video_id}.txt"
    async with aiofiles.open(out_file, "w", encoding="utf-8") as fh:
        await fh.write(text)

    return {
        "status": "ok",
        "video_id": video_id,
        "job_id": job_id,
        "files": [out_file.name],
        "count": 1,
        "source": transcript.get("source"),
        "cached": bool(transcript.get("cached")),
        "title": transcript.get("title"),
        "channel": transcript.get("channel"),
        "language": transcript.get("language"),
        "chars": len(text),
    }


# ---------------------------------------------------------------------------
# 2. Генерация рецепта через LLM
# ---------------------------------------------------------------------------

@router.post("/api/generate-recipe")
async def generate_recipe(
    request: Request,
    job_id: str = Form(...),
    save: bool = Form(False),
    link: bool = Form(True),
):
    """Генерирует Markdown-рецепт по транскрипту.

    Параметры:
        job_id  — идентификатор, полученный от /api/download
        save    — если True, рецепт сразу сохраняется в базу
        link    — если True (по умолчанию) и save=True, прогоняется
                  через linker для связки product-блоков
    """
    _require_enabled()

    _pattern = re.compile(rf"^{re.escape(job_id)}_")
    files = [
        p
        for p in DOWNLOAD_DIR.iterdir()
        if p.is_file()
        and _pattern.match(p.name)
        and p.suffix in (".txt", ".srt", ".vtt")
    ]
    files.sort()
    if not files:
        raise HTTPException(
            404,
            detail={"error": "Транскрипт не найден", "job_id": job_id},
        )

    combined_text = ""
    for f in files:
        async with aiofiles.open(f, "r", encoding="utf-8") as fh:
            raw = await fh.read()
        combined_text += (clean_srt_text(raw) if f.suffix != ".txt" else raw) + "\n\n"

    if not combined_text.strip():
        raise HTTPException(400, "Не удалось извлечь текст из транскрипта")

    from services.auth import get_current_user

    _u = get_current_user(request)
    _user_id = _u.get("id") if _u else None
    markdown, used_model = await call_gemini(combined_text, user_id=_user_id)

    # YouTube-обложка — это кадр из видео (часто автор/превью), а не фото
    # блюда. Не подставляем её в рецепт; пользователь добавит фото вручную.
    markdown = re.sub(r"(?m)^\s*image_url\s*:.*$", "image_url: null", markdown)

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

    if save:
        try:
            parsed = parse_markdown_recipe(markdown)
        except ValueError as exc:
            logger.warning("Не удалось распарсить MD от LLM: %s", exc)
            result["save_error"] = f"markdown_parse_failed: {exc}"
            return result

        if link:
            try:
                parsed = await link_recipe_ingredients(parsed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Linker упал при save из YouTube: %s", exc)

        parsed["image_url"] = None
        parsed.pop("_linker_stats", None)

        try:
            recipe = await recipe_store.add(parsed)
            result["recipe"] = recipe
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось сохранить рецепт из YouTube: %s", exc)
            result["save_error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# 3. Диагностика: последние задания и кэш
# ---------------------------------------------------------------------------

@router.get("/api/youtube/jobs")
async def list_jobs():
    files = sorted(
        DOWNLOAD_DIR.glob("*_recipe.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files[:50]:
        name = f.name
        m = re.match(r"^([a-f0-9]{8})_", name)
        job_id = m.group(1) if m else None
        texts = (
            [
                p.name
                for p in DOWNLOAD_DIR.iterdir()
                if p.is_file()
                and job_id
                and p.name.startswith(f"{job_id}_")
                and p.suffix in (".txt", ".srt", ".vtt")
            ]
            if job_id
            else []
        )
        result.append({
            "job_id": job_id,
            "md_file": name,
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime,
            "transcripts": texts,
        })
    return {"jobs": result, "count": len(result)}


@router.delete("/api/youtube/cache/{video_id}")
async def delete_cached_transcript(request: Request, video_id: str):
    """Удаляет транскрипт из кэша (админ)."""
    _require_admin(request)
    deleted = await youtube_transcripts.delete(video_id)
    return {"video_id": video_id, "deleted": deleted}
