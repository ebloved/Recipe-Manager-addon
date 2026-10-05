"""Синхронизация файла рецептов с GitHub."""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from config import (
    GITHUB_BRANCH,
    GITHUB_PATH,
    GITHUB_REPO,
    GITHUB_TOKEN,
    GITHUB_USERNAME,
)

_API = "https://api.github.com"


# --- Нормализация входных данных -------------------------------------------

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
    raw_repo = GITHUB_REPO
    repo = _normalize_repo(raw_repo)

    if not repo or "/" not in repo or repo.count("/") != 1:
        raise HTTPException(
            400,
            f"Некорректный github_repo: '{raw_repo}'. "
            "Ожидается формат 'owner/repo' (например, 'ebloved/recipe-manager-data').",
        )

    if not GITHUB_TOKEN:
        raise HTTPException(400, "Не задан github_token")

    branch = (GITHUB_BRANCH or "main").strip() or "main"
    path = (GITHUB_PATH or "recipes.json").strip().lstrip("/") or "recipes.json"
    return repo, GITHUB_TOKEN, branch, path, GITHUB_USERNAME


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "HomeAssistant-RecipeManager/1.0",
    }


# --- Проверки доступа -------------------------------------------------------

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
    """Проверяет, что ветка существует. Возвращает True/False."""
    url = f"{_API}/repos/{repo}/branches/{branch}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=_headers(token))
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    return False


# --- Работа с файлом --------------------------------------------------------

async def _get_file(repo: str, path: str, branch: str, token: str) -> dict | None:
    """Возвращает {content, sha, encoding} или None, если файла нет."""
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


async def pull_recipes() -> str:
    """Возвращает содержимое файла из GitHub как строку."""
    repo, token, branch, path, _ = _check_config()

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


async def push_recipes(content: str, message: str | None = None) -> dict[str, Any]:
    """Загружает content в repo/path/branch. Создаёт или обновляет файл."""
    repo, token, branch, path, username = _check_config()

    await _check_repo_access(repo, token)

    if not await _check_branch(repo, branch, token):
        raise HTTPException(
            404,
            f"GitHub: ветка '{branch}' не найдена в '{repo}'. "
            f"Создайте ветку или укажите существующую в настройке github_branch.",
        )

    if not message:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        who = username or "recipe-manager"
        message = f"chore: sync recipes.json ({who}, {ts})"

    info = await _get_file(repo, path, branch, token)
    payload: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if info and info.get("sha"):
        payload["sha"] = info["sha"]

    url = f"{_API}/repos/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.put(url, headers=_headers(token), json=payload)

    if resp.status_code in (200, 201):
        data = resp.json()
        commit = data.get("commit") or {}
        return {
            "commit_sha": commit.get("sha"),
            "html_url": commit.get("html_url"),
            "updated": bool(info),
        }
    if resp.status_code == 401:
        raise HTTPException(401, "GitHub: неверный токен")
    if resp.status_code == 403:
        raise HTTPException(403, "GitHub: недостаточно прав (нужен Contents: Read and write)")
    if resp.status_code == 409:
        raise HTTPException(409, "GitHub: конфликт версий, попробуйте ещё раз")
    if resp.status_code == 404:
        raise HTTPException(
            404,
            f"GitHub PUT вернул 404. Проверьте: имя репозитория, права токена "
            f"(Contents: Read and write), существует ли ветка '{branch}'.",
        )
    raise HTTPException(resp.status_code, f"GitHub PUT {resp.status_code}: {resp.text[:200]}")


async def status() -> dict[str, Any]:
    """Возвращает конфигурацию и текущее состояние файла в GitHub."""
    repo, token, branch, path, _ = _check_config()

    repo_info = await _check_repo_access(repo, token)
    branch_exists = await _check_branch(repo, branch, token)

    info = None
    if branch_exists:
        info = await _get_file(repo, path, branch, token)

    return {
        "repo": repo,
        "branch": branch,
        "path": path,
        "private": bool(repo_info.get("private")),
        "default_branch": repo_info.get("default_branch"),
        "branch_exists": branch_exists,
        "exists": bool(info),
        "sha": (info or {}).get("sha"),
        "size": (info or {}).get("size"),
    }