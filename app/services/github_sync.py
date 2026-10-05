"""Синхронизация файла рецептов с GitHub."""
from __future__ import annotations

import base64
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


def _check_config() -> tuple[str, str, str, str, str]:
    if not GITHUB_REPO or "/" not in GITHUB_REPO:
        raise HTTPException(400, "Не задан github_repo (формат: user/repo)")
    if not GITHUB_TOKEN:
        raise HTTPException(400, "Не задан github_token")
    return GITHUB_REPO, GITHUB_TOKEN, GITHUB_BRANCH, GITHUB_PATH, GITHUB_USERNAME


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "HomeAssistant-RecipeManager/1.0",
    }


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
    raise HTTPException(resp.status_code, f"GitHub PUT {resp.status_code}: {resp.text[:200]}")


async def status() -> dict[str, Any]:
    """Возвращает конфигурацию и текущее состояние файла в GitHub."""
    repo, token, branch, path, _ = _check_config()
    info = await _get_file(repo, path, branch, token)
    return {
        "repo": repo,
        "branch": branch,
        "path": path,
        "exists": bool(info),
        "sha": (info or {}).get("sha"),
        "size": (info or {}).get("size"),
    }