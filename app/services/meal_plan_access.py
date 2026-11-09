"""Доступ к генерации меню на неделю."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from stores.settings import settings_store

_VALUES = ("off", "admin", "all")


def get_access() -> str:
    value = str(settings_store.get("meal_plan_gen_access", "off") or "off").lower()
    return value if value in _VALUES else "off"


def can_use(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    access = get_access()
    if access == "all":
        return True
    if access == "admin":
        return user.get("role") == "admin"
    return False


def require_access(user: dict[str, Any] | None) -> None:
    if not can_use(user):
        raise HTTPException(403, "Генерация меню недоступна")
