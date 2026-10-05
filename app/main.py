"""Recipe Manager — FastAPI backend для HA add-on.

Объединяет:
- генерацию рецептов из YouTube Shorts (yt-dlp + Gemini)
- импорт рецептов из Markdown, по URL и вручную
- парсинг рецептов с веб-сайтов через recipe-scrapers
- библиотеку рецептов с поиском
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
import httpx
from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# --- Recipe Manager core --------------------------------------------------
from recipe_manager.importer import parse_markdown_recipe

# --- Paths and env --------------------------------------------------------

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
RECIPES_FILE = DATA_DIR / "recipes.json"

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_FILE = BASE_DIR / "recipe_template.md"
STATIC_DIR = BASE_DIR / "static"

_TEMPLATE_CACHE: str | None = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash",
    ).split(",")
    if m.strip()
]
GEMINI_PROXY = os.environ.get("GEMINI_PROXY") or None
SUB_LANGS = os.environ.get("SUB_LANGS", "ru.*")
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None


# --- Recipe store ---------------------------------------------------------

class RecipeStore:
    """Simple JSON-file backed store for recipes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.recipes: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                self.recipes = data.get("recipes", [])
            except Exception as exc:  # noqa: BLE001
                print(f"[recipes] failed to load {self.path}: {exc}")
                self.recipes = []

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(
                    json.dumps(
                        {"recipes": self.recipes},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            tmp.replace(self.path)

    def get_all(self) -> list[dict[str, Any]]:
        return list(self.recipes)

    def get(self, recipe_id: str) -> dict[str, Any] | None:
        return next((r for r in self.recipes if r.get("id") == recipe_id), None)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        recipe = {
            "id": uuid.uuid4().hex,
            "created_at": now,
            "updated_at": now,
            **data,
        }
        self.recipes.append(recipe)
        await self.save()
        return recipe

    async def update(
        self, recipe_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        for i, r in enumerate(self.recipes):
            if r.get("id") == recipe_id:
                updated = {
                    **r,
                    **patch,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.recipes[i] = updated
                await self.save()
                return updated
        return None

    async def delete(self, recipe_id: str) -> bool:
        before = len(self.recipes)
        self.recipes = [r for r in self.recipes if r.get("id") != recipe_id]
        if len(self.recipes) < before:
            await self.save()
            return True
        return False

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for r in self.recipes:
            for t in r.get("tags") or []:
                if isinstance(t, str) and t.strip():
                    tags.add(t.strip())
        return sorted(tags)


recipe_store = RecipeStore(RECIPES_FILE)


# --- Lifespan -------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await recipe_store.load()
    print(f"[recipes] loaded {len(recipe_store.recipes)} recipes from {RECIPES_FILE}")
    yield


# --- App ------------------------------------------------------------------

app = FastAPI(title="Recipe Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_template() -> str:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        if TEMPLATE_FILE.exists():
            _TEMPLATE_CACHE = TEMPLATE_FILE.read_text(encoding="utf-8")
            print(f"[template] loaded from {TEMPLATE_FILE}, {len(_TEMPLATE_CACHE)} bytes")
        else:
            _TEMPLATE_CACHE = ""
            print(f"[template] NOT FOUND at {TEMPLATE_FILE}")
    return _TEMPLATE_CACHE


# --- Ingress middleware ---------------------------------------------------

@app.middleware("http")
async def ingress_middleware(request: Request, call_next):
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if ingress_path:
        request.scope["root_path"] = ingress_path
    return await call_next(request)


# --- Helpers --------------------------------------------------------------

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
        if line == prev:
            continue
        if line in prev:
            continue
        if prev in line:
            cleaned[-1] = line
            continue
        cleaned.append(line)
    return " ".join(cleaned)


async def run_ytdlp(url: str, job_id: str) -> dict:
    outtmpl = str(DOWNLOAD_DIR / f"{job_id}_%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
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
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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


RECIPE_PROMPT = """Ты — редактор кулинарных рецептов.

Тебе дан текст из субтитров YouTube Shorts (возможно, с ошибками распознавания речи) и пример правильно оформленного рецепта в формате YAML front matter + Markdown.

Оформи результат в ТОЧНО ТАКОЙ ЖЕ структуре, как в примере ниже:
- тот же набор полей в YAML front matter;
- та же разбивка на секции (Ингредиенты / Шаги / Заметки);
- тот же стиль записи количеств («500 г», «2 ст. л.», «по вкусу»);
- те же ключи nutrition, если есть данные.

Жёсткие правила:
1. Исправляй только очевидные ошибки распознавания речи.
2. НЕ выдумывай ингредиенты, количества, время, температуру и названия блюд, которых нет в тексте. Если ингредиент упомянут обобщённо («колбаска», «сыр»), пиши его как в тексте, без уточнений.
3. Если каких-то полей нет — ставь `null` в YAML или «не указано» в тексте.
4. Верни ТОЛЬКО итоговый Markdown, без пояснений и без обрамляющих ```.

Пример оформления:

{template}

Текст субтитров:

{text}
"""


async def call_gemini(text: str) -> tuple[str, str]:
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY не задан в настройках add-on")

    template = _load_template()
    prompt = RECIPE_PROMPT.format(template=template, text=text)

    last_error: Exception | None = None

    client_kwargs: dict = {"timeout": 60.0}
    if GEMINI_PROXY:
        client_kwargs["proxy"] = GEMINI_PROXY

    async with httpx.AsyncClient(**client_kwargs) as client:
        for model in GEMINI_MODELS:
            for attempt in range(1, 4):
                try:
                    url = (
                        "https://generativelanguage.googleapis.com/v1beta/"
                        f"models/{model}:generateContent?key={GEMINI_API_KEY}"
                    )
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": 2000,
                        },
                    }
                    resp = await client.post(url, json=payload)
                    if resp.status_code in (503, 429):
                        raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
                    resp.raise_for_status()
                    data = resp.json()

                    markdown = (
                        data["candidates"][0]["content"]["parts"][0]["text"]
                    ).strip()
                    if markdown.startswith("```"):
                        markdown = re.sub(r"^```[a-zA-Z]*\n", "", markdown)
                        markdown = re.sub(r"\n```$", "", markdown)
                    return markdown.strip(), model

                except Exception as e:  # noqa: BLE001
                    last_error = e
                    print(f"[gemini] model={model} attempt={attempt} failed: {e}")
                    if attempt < 3:
                        await asyncio.sleep(2**attempt)

    raise HTTPException(502, f"Все модели недоступны: {last_error}")


async def fetch_markdown(url: str) -> str:
    headers = {
        "User-Agent": "HomeAssistant-RecipeManager/1.0",
        "Accept": "text/markdown,text/plain,text/*;q=0.9,*/*;q=0.5",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(502, f"HTTP {resp.status_code} fetching {url}")
        return resp.text


# --- Web scrape -----------------------------------------------------------

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def _first_or_str(v: Any) -> str | None:
    if not v:
        return None
    if isinstance(v, list):
        return str(v[0]).strip() if v else None
    return str(v).strip()


def _to_int_minutes(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _extract_servings_count(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d+", str(text))
    return int(m.group()) if m else None


async def scrape_recipe(url: str) -> dict[str, Any]:
    """Scrape a recipe from a URL using recipe-scrapers."""
    try:
        from recipe_scrapers import scrape_html  # type: ignore[import]
    except ImportError as exc:
        raise HTTPException(500, f"recipe-scrapers not installed: {exc}") from exc

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=_SCRAPE_HEADERS
    ) as client:
        try:
            resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"fetch_failed: {exc}") from exc
        if resp.status_code != 200:
            raise HTTPException(502, f"HTTP {resp.status_code} fetching {url}")
        html = resp.text

    try:
        scraper = scrape_html(html, org_url=url, wild_mode=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"scrape_failed: {exc}") from exc

    name = (_safe(scraper.title) or "").strip()
    if not name:
        raise HTTPException(502, "Не удалось извлечь название рецепта")

    ingredients_raw = _safe(scraper.ingredients) or []
    ingredients = [str(s).strip() for s in ingredients_raw if s and str(s).strip()]

    instructions = _safe(scraper.instructions_list) or []
    if not instructions:
        raw = _safe(scraper.instructions) or ""
        instructions = [s.strip() for s in str(raw).split("\n") if s.strip()]

    servings_text = _safe(scraper.yields)
    servings = _extract_servings_count(servings_text)

    keywords = _safe(scraper.keywords) or []
    if isinstance(keywords, str):
        tags = [t.strip().lower() for t in keywords.split(",") if t.strip()]
    else:
        tags = [str(t).strip().lower() for t in keywords if str(t).strip()]

    return {
        "name": name,
        "description": _safe(scraper.description),
        "source_url": url,
        "image_url": _safe(scraper.image),
        "servings": servings,
        "servings_text": str(servings_text) if servings_text else None,
        "prep_time": _to_int_minutes(_safe(scraper.prep_time)),
        "cook_time": _to_int_minutes(_safe(scraper.cook_time)),
        "total_time": _to_int_minutes(_safe(scraper.total_time)),
        "cuisine": _first_or_str(_safe(scraper.cuisine)),
        "category": _first_or_str(_safe(scraper.category)),
        "ingredients": ingredients,
        "instructions": instructions,
        "tags": tags,
    }


# --- API: yt-subs ---------------------------------------------------------

@app.post("/api/download")
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


@app.post("/api/generate-recipe")
async def generate_recipe(job_id: str = Form(...)):
    files = sorted(
        list(DOWNLOAD_DIR.glob(f"{job_id}_*.srt"))
        + list(DOWNLOAD_DIR.glob(f"{job_id}_*.vtt"))
    )
    if not files:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Субтитры для этого job_id не найдены",
                "job_id": job_id,
                "available_files": sorted(f.name for f in DOWNLOAD_DIR.iterdir()),
            },
        )

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
        "sources_used": [f.name for f in files],
        "markdown": markdown,
        "file": out_file.name,
        "download_url": f"files/{out_file.name}",
    }


# --- API: recipes ---------------------------------------------------------

@app.get("/api/recipes")
async def list_recipes(q: str | None = None):
    items = recipe_store.get_all()
    if q:
        lower = q.strip().lower()

        def matches(r: dict[str, Any]) -> bool:
            if lower in (r.get("name") or "").lower():
                return True
            if lower in (r.get("description") or "").lower():
                return True
            for key in ("tags", "courses", "categories", "collections"):
                for v in r.get(key) or []:
                    if isinstance(v, str) and lower in v.lower():
                        return True
            for ing in r.get("ingredients") or []:
                name = ing.get("name") if isinstance(ing, dict) else str(ing)
                if name and lower in str(name).lower():
                    return True
            return False

        items = [r for r in items if matches(r)]
    return {"recipes": items, "count": len(items)}


@app.get("/api/recipes/{recipe_id}")
async def get_recipe(recipe_id: str):
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


@app.post("/api/recipes")
async def create_recipe(payload: dict[str, Any] = Body(...)):
    md = payload.get("markdown_content")
    explicit = {k: v for k, v in payload.items() if k != "markdown_content"}

    if md:
        try:
            parsed = parse_markdown_recipe(md)
        except ValueError as exc:
            raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc
        data = {**parsed, **explicit}
    else:
        if not explicit.get("name"):
            raise HTTPException(
                400, "Either 'name' or 'markdown_content' is required"
            )
        data = explicit

    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


@app.post("/api/recipes/import-url")
async def import_recipe_from_url(url: str = Form(...)):
    try:
        content = await fetch_markdown(url)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"fetch_failed: {exc}") from exc

    try:
        data = parse_markdown_recipe(content)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    recipe = await recipe_store.add(data)
    return {"recipe": recipe}


@app.post("/api/scrape")
async def api_scrape(url: str = Form(...)):
    """Scrape a recipe from a URL and return the parsed data (not saved)."""
    data = await scrape_recipe(url)
    return {"recipe": data}


@app.patch("/api/recipes/{recipe_id}")
async def update_recipe(recipe_id: str, patch: dict[str, Any] = Body(...)):
    recipe = await recipe_store.update(recipe_id, patch)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


@app.delete("/api/recipes/{recipe_id}")
async def delete_recipe(recipe_id: str):
    ok = await recipe_store.delete(recipe_id)
    if not ok:
        raise HTTPException(404, "Recipe not found")
    return {"deleted": True}


@app.get("/api/tags")
async def list_tags():
    return {"tags": recipe_store.all_tags()}


# --- API: files, health, debug -------------------------------------------

@app.get("/files/{filename}")
async def get_file(filename: str):
    safe = Path(filename).name
    path = DOWNLOAD_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Файл не найден")

    if safe.endswith(".md"):
        media = "text/markdown; charset=utf-8"
    elif safe.endswith(".srt"):
        media = "application/x-subrip"
    elif safe.endswith(".vtt"):
        media = "text/vtt; charset=utf-8"
    else:
        media = "application/octet-stream"

    return FileResponse(path, media_type=media, filename=safe)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "models": GEMINI_MODELS,
        "proxy": bool(GEMINI_PROXY),
        "api_key": bool(GEMINI_API_KEY),
        "sub_langs": SUB_LANGS,
        "cookies": bool(COOKIES_FILE and os.path.exists(COOKIES_FILE)),
        "recipes": len(recipe_store.recipes),
        "data_file": str(RECIPES_FILE),
    }


@app.get("/api/debug-template")
async def debug_template():
    tmpl = _load_template()
    return {
        "path": str(TEMPLATE_FILE),
        "exists": TEMPLATE_FILE.exists(),
        "length": len(tmpl),
        "preview": tmpl[:200],
    }


# --- Web UI ---------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    async with aiofiles.open(STATIC_DIR / "index.html", "r", encoding="utf-8") as f:
        return await f.read()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")