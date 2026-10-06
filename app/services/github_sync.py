"""Синхронизация файлов состояния с GitHub.

Поддерживает два файла:
  - recipes.json      (путь: GITHUB_PATH, по умолчанию "recipes.json")
  - ingredients.json  (путь: GITHUB_INGREDIENTS_PATH, по умолчанию "ingredients.json")

Ключевое отличие от предыдущей версии:
  Push идёт через Git Data API и создаёт ОДИН коммит на все файлы.
  Contents API (PUT /contents/{path}) умеет только один файл за коммит,
  и при параллельной записи двух файлов между ними может попасть
  промежуточное состояние. Git Data API даёт атомарность: либо оба
  файла обновились, либо ни один.

  Pull читает файлы через Contents API (по одному) — этого достаточно,
  потому что на чтение атомарность не нужна.

Публичные функции:
    push_many(files, message=None) -> dict
    pull_one(path)                 -> str
    status()                       -> dict

Совместимость:
    pull_recipes() и push_recipes() оставлены как обёртки для обратной
    совместимости на случай, если где-то ещё вызываются.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from config import (
    GITHUB_BRANCH,
    GITHUB_INGREDIENTS_PATH,
    GITHUB_PATH,
    GITHUB_REPO,
    GITHUB_TOKEN,
    GITHUB_USERNAME,
)

logger = logging.getLogger(__name__)

_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Нормализация и валидация конфига
# ---------------------------------------------------------------------------

def _normalize_repo(raw: str) -> str:
    """Приводит github_repo к формату 'owner/repo'.

    Принимает:
      - 'user/repo'
      - 'user/repo.git'
      - 'https://github.com/user/repo'
      - 'https://github.com/user/repo/'
      - 'https://github.com/user/repo.git'
      - 'git@github.com:user/repo.git'
    """
    s = (raw or "").strip()
    if not s:
        return ""

    # git@github.com:owner/repo.git
    m = re.match(r"^git@[^:]+:(.+?)(?:\.git)?$", s)
    if m:
        return m.group(1).strip("/")

    # https://github.com/owner/repo[/][.git]
    m = re.match(r"^https?://[^/]+/(.+?)(?:\.git)?/?$", s)
    if m:
        return m.group(1).strip("/")

    # owner/repo.git
    s = re.sub(r"\.git$", "", s)
    return s.strip("/")


def _check_config() -> tuple[str, str, str, str, str]:
    """Валидирует конфиг, возвращает (repo, token, branch, recipes_path, ingredients_path)."""
    raw_repo = GITHUB_REPO
    repo = _normalize_repo(raw_repo)

    if not repo or "/" not in repo or repo.count("/") != 1:
        raise HTTPException(
            400,
            f"Некорректный github_repo: '{raw_repo}'. "
            "Ожидается формат 'owner/repo' (например, 'user/recipe-manager-data').",
        )

    if not GITHUB_TOKEN:
        raise HTTPException(400, "Не задан github_token")

    branch = (GITHUB_BRANCH or "main").strip() or "main"
    recipes_path = (GITHUB_PATH or "recipes.json").strip().lstrip("/") or "recipes.json"
    ingredients_path = (
        (GITHUB_INGREDIENTS_PATH or "ingredients.json").strip().lstrip("/")
        or "ingredients.json"
    )

    return repo, GITHUB_TOKEN, branch, recipes_path, ingredients_path


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "HomeAssistant-RecipeManager/1.0",
    }


# ---------------------------------------------------------------------------
# Проверки доступа
# ---------------------------------------------------------------------------

async def _check_repo_access(repo: str, token: str) -> dict:
    """Проверяет, что токен видит репозиторий. Возвращает info или бросает HTTPException."""
    url = f"{_API}/repos/{repo}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=_headers(token))

    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 401:
        raise HTTPException(401, "GitHub: неверный или просроченный токен")
    if resp.status_code == 404:
        raise HTTPException(
            404,
            f"GitHub: репозиторий '{repo}' не найден или недоступен этому токену. "
            "Проверьте: 1) имя repo в формате 'owner/repo'; "
            "2) в настройках fine-grained токена репозиторий добавлен в 'Repository access'; "
            "3) у токена есть право 'Contents: Read and write'.",
        )
    if resp.status_code == 403:
        raise HTTPException(403, f"GitHub: доступ запрещён (HTTP 403). {resp.text[:200]}")
    raise HTTPException(resp.status_code, f"GitHub GET /repos/{repo}: {resp.status_code}: {resp.text[:200]}")


async def _check_branch(repo: str, branch: str, token: str) -> bool:
    """Проверяет, что ветка существует."""
    url = f"{_API}/repos/{repo}/branches/{branch}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=_headers(token))
    return resp.status_code == 200


# ---------------------------------------------------------------------------
# Contents API — чтение одного файла
# ---------------------------------------------------------------------------

async def _get_file(repo: str, path: str, branch: str, token: str) -> dict | None:
    """Возвращает {content, sha, encoding, size} или None, если файла нет."""
    url = f"{_API}/repos/{repo}/contents/{path}"
    params = {"ref": branch}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=_headers(token), params=params)

    if resp.status_code == 404:
        return None
    if resp.status_code == 401:
        raise HTTPException(401, "GitHub: неверный токен")
    if resp.status_code == 403:
        raise HTTPException(403, "GitHub: недостаточно прав у токена (нужен Contents: Read and write)")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"GitHub GET {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def pull_one(path: str) -> str:
    """Возвращает содержимое файла из GitHub как строку.

    path: имя файла (или путь в репозитории). Например, 'recipes.json'
          или 'ingredients.json'. Если path не указан явно — используется
          GITHUB_PATH.

    Бросает HTTPException(404), если файла нет.
    """
    repo, token, branch, recipes_path, ingredients_path = _check_config()

    # Если передан recipes.json или ingredients.json — подменяем на актуальный путь из конфига
    if path in ("recipes.json", GITHUB_PATH):
        path = recipes_path
    elif path in ("ingredients.json", GITHUB_INGREDIENTS_PATH):
        path = ingredients_path
    else:
        path = path.strip().lstrip("/")

    await _check_repo_access(repo, token)

    if not await _check_branch(repo, branch, token):
        raise HTTPException(
            404,
            f"GitHub: ветка '{branch}' не найдена в '{repo}'. "
            f"Создайте ветку или укажите существующую в настройке github_branch.",
        )

    info = await _get_file(repo, path, branch, token)
    if not info:
        raise HTTPException(404, f"Файл {path} не найден в {repo}@{branch}")

    if info.get("encoding") == "base64":
        try:
            return base64.b64decode(info["content"]).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Не удалось декодировать файл: {exc}") from exc

    dl = info.get("download_url")
    if dl:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(dl)
            if r.status_code == 200:
                return r.text
    raise HTTPException(500, "Не удалось получить содержимое файла")


# ---------------------------------------------------------------------------
# Git Data API — атомарный коммит нескольких файлов
# ---------------------------------------------------------------------------

async def _get_ref_sha(repo: str, branch: str, token: str) -> str:
    """Возвращает commit SHA последнего коммита в ветке."""
    url = f"{_API}/repos/{repo}/git/ref/heads/{branch}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=_headers(token))
    if resp.status_code == 404:
        raise HTTPException(
            404,
            f"GitHub: ветка '{branch}' не найдена в '{repo}'.",
        )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"GitHub ref: {resp.text[:200]}")
    return resp.json()["object"]["sha"]


async def _get_commit_tree_sha(repo: str, commit_sha: str, token: str) -> str:
    """Возвращает tree SHA коммита."""
    url = f"{_API}/repos/{repo}/git/commits/{commit_sha}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=_headers(token))
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"GitHub commit: {resp.text[:200]}")
    return resp.json()["tree"]["sha"]


async def _create_blob(repo: str, content: str, token: str) -> str:
    """Создаёт blob с содержимым файла. Возвращает blob SHA."""
    url = f"{_API}/repos/{repo}/git/blobs"
    payload = {
        "content": content,
        "encoding": "utf-8",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=_headers(token), json=payload)
    if resp.status_code not in (200, 201):
        raise HTTPException(resp.status_code, f"GitHub blob: {resp.text[:200]}")
    return resp.json()["sha"]


async def _create_tree(
    repo: str,
    base_tree_sha: str,
    entries: list[dict[str, str]],
    token: str,
) -> str:
    """Создаёт новый tree на основе base + переданных entries.

    entries: [{"path": "recipes.json", "mode": "100644", "type": "blob", "sha": "..."}]
    """
    url = f"{_API}/repos/{repo}/git/trees"
    payload = {
        "base_tree": base_tree_sha,
        "tree": entries,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=_headers(token), json=payload)
    if resp.status_code not in (200, 201):
        raise HTTPException(resp.status_code, f"GitHub tree: {resp.text[:200]}")
    return resp.json()["sha"]


async def _create_commit(
    repo: str,
    tree_sha: str,
    parent_sha: str,
    message: str,
    token: str,
) -> dict:
    """Создаёт коммит. Возвращает {sha, html_url}."""
    url = f"{_API}/repos/{repo}/git/commits"
    payload = {
        "message": message,
        "tree": tree_sha,
        "parents": [parent_sha],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=_headers(token), json=payload)
    if resp.status_code not in (200, 201):
        raise HTTPException(resp.status_code, f"GitHub commit: {resp.text[:200]}")
    data = resp.json()
    return {"sha": data["sha"], "html_url": data.get("html_url")}


async def _update_ref(
    repo: str,
    branch: str,
    new_commit_sha: str,
    token: str,
) -> None:
    """Обновляет ref ветки на новый commit SHA."""
    url = f"{_API}/repos/{repo}/git/refs/heads/{branch}"
    payload = {"sha": new_commit_sha, "force": False}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(url, headers=_headers(token), json=payload)
    if resp.status_code not in (200, 201):
        if resp.status_code == 409:
            raise HTTPException(
                409,
                "GitHub: конфликт версий. Кто-то другой обновил ветку — "
                "сделайте pull, затем повторите push.",
            )
        raise HTTPException(resp.status_code, f"GitHub ref update: {resp.text[:200]}")


async def push_many(
    files: dict[str, str],
    message: str | None = None,
) -> dict[str, Any]:
    """Атомарно коммитит несколько файлов одним коммитом.

    files: {путь_в_репе: содержимое_как_строка}
      Например: {"recipes.json": "...", "ingredients.json": "..."}

    Возвращает:
      {
        "commit_sha": "...",
        "html_url": "https://github.com/.../commit/...",
        "files": [{"path": "...", "blob_sha": "...", "size": N}, ...]
      }
    """
    if not files:
        raise HTTPException(400, "Нечего коммитить: files пуст")

    repo, token, branch, recipes_path, ingredients_path = _check_config()

    await _check_repo_access(repo, token)

    if not await _check_branch(repo, branch, token):
        raise HTTPException(
            404,
            f"GitHub: ветка '{branch}' не найдена в '{repo}'. "
            f"Создайте ветку или укажите существующую в настройке github_branch.",
        )

    # Нормализуем имена файлов: recipes.json / ingredients.json → реальные пути
    normalized: dict[str, str] = {}
    for name, content in files.items():
        if name in ("recipes.json", GITHUB_PATH):
            real = recipes_path
        elif name in ("ingredients.json", GITHUB_INGREDIENTS_PATH):
            real = ingredients_path
        else:
            real = name.strip().lstrip("/")
        normalized[real] = content

    # 1. Получаем SHA текущего коммита и его tree
    parent_sha = await _get_ref_sha(repo, branch, token)
    base_tree_sha = await _get_commit_tree_sha(repo, parent_sha, token)

    # 2. Создаём blobs для каждого файла
    blob_entries: list[dict[str, str]] = []
    file_stats: list[dict[str, Any]] = []
    for path, content in normalized.items():
        blob_sha = await _create_blob(repo, content, token)
        blob_entries.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha,
        })
        file_stats.append({
            "path": path,
            "blob_sha": blob_sha,
            "size": len(content.encode("utf-8")),
        })

    # 3. Создаём новый tree поверх base_tree
    new_tree_sha = await _create_tree(repo, base_tree_sha, blob_entries, token)

    # 4. Формируем сообщение коммита
    if not message:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        who = GITHUB_USERNAME or "recipe-manager"
        paths = ", ".join(normalized.keys())
        message = f"chore: sync {paths} ({who}, {ts})"

    # 5. Создаём коммит
    commit_info = await _create_commit(repo, new_tree_sha, parent_sha, message, token)

    # 6. Обновляем ref ветки
    await _update_ref(repo, branch, commit_info["sha"], token)

    logger.info(
        "GitHub push: %d файлов, commit=%s",
        len(normalized), commit_info["sha"][:7],
    )

    return {
        "commit_sha": commit_info["sha"],
        "html_url": commit_info.get("html_url"),
        "files": file_stats,
        "updated": True,
    }


# ---------------------------------------------------------------------------
# Общая информация
# ---------------------------------------------------------------------------

async def status() -> dict[str, Any]:
    """Возвращает конфиг и текущее состояние обоих файлов в GitHub."""
    repo, token, branch, recipes_path, ingredients_path = _check_config()

    repo_info = await _check_repo_access(repo, token)
    branch_exists = await _check_branch(repo, branch, token)

    def _file_status(info: dict | None) -> dict[str, Any]:
        if not info:
            return {"exists": False, "sha": None, "size": None}
        return {
            "exists": True,
            "sha": info.get("sha"),
            "size": info.get("size"),
        }

    recipes_info: dict | None = None
    ingredients_info: dict | None = None
    if branch_exists:
        try:
            recipes_info = await _get_file(repo, recipes_path, branch, token)
        except HTTPException:
            recipes_info = None
        try:
            ingredients_info = await _get_file(repo, ingredients_path, branch, token)
        except HTTPException:
            ingredients_info = None

    return {
        "repo": repo,
        "branch": branch,
        "private": bool(repo_info.get("private")),
        "default_branch": repo_info.get("default_branch"),
        "branch_exists": branch_exists,
        "files": {
            "recipes.json": {
                "path": recipes_path,
                **_file_status(recipes_info),
            },
            "ingredients.json": {
                "path": ingredients_path,
                **_file_status(ingredients_info),
            },
        },
    }


# ---------------------------------------------------------------------------
# Обратная совместимость
#
# Эти обёртки оставлены, чтобы не ломать другие модули, если они ещё
# используют старый API. В новых вызовах используйте pull_one / push_many.
# ---------------------------------------------------------------------------

async def pull_recipes() -> str:
    """Забрать recipes.json (обёртка над pull_one для совместимости)."""
    return await pull_one("recipes.json")


async def push_recipes(content: str, message: str | None = None) -> dict[str, Any]:
    """Залить recipes.json (обёртка над push_many для совместимости)."""
    return await push_many({"recipes.json": content}, message=message)