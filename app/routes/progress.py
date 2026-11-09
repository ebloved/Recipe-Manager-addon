"""Личный прогресс: рост, вес, цель и BMI-ориентир.

Стадия 1: доступно только администраторам. Это не медицинская рекомендация.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from stores.progress import progress_store

router = APIRouter(prefix="/api/progress", tags=["progress"])


def _user(request: Request) -> dict[str, Any] | None:
    return get_current_user(request)


def _require_admin(user: dict[str, Any] | None) -> None:
    if not user:
        raise HTTPException(401, "Unauthorized")
    if user.get("role") != "admin":
        raise HTTPException(403, "Прогресс доступен только администраторам")


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _category(bmi: float) -> dict[str, str]:
    if bmi < 18.5:
        return {"id": "low", "label": "Ниже нормы", "range": "< 18.5"}
    if bmi < 25:
        return {"id": "normal", "label": "В пределах нормы", "range": "18.5–24.9"}
    if bmi < 30:
        return {"id": "above", "label": "Выше нормы", "range": "25–29.9"}
    return {"id": "high", "label": "Значительно выше нормы", "range": "30+"}


def _metrics(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data:
        return None
    height = _num(data.get("height_cm"))
    weight = _num(data.get("weight_kg"))
    if not height or not weight:
        return None
    meters = height / 100.0
    bmi = weight / (meters * meters)
    target = _num(data.get("target_weight_kg"))
    target_bmi = target / (meters * meters) if target else None
    return {
        "height_cm": round(height, 1),
        "weight_kg": round(weight, 1),
        "target_weight_kg": round(target, 1) if target else None,
        "bmi": round(bmi, 1),
        "category": _category(bmi),
        "healthy_range_kg": {
            "min": round(18.5 * meters * meters, 1),
            "max": round(24.9 * meters * meters, 1),
        },
        "target_bmi": round(target_bmi, 1) if target_bmi else None,
        "target_category": _category(target_bmi) if target_bmi else None,
    }


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if "height_cm" in payload:
        height = _num(payload.get("height_cm"))
        if height is None or not (100 <= height <= 250):
            raise HTTPException(400, "Рост должен быть от 100 до 250 см")
        patch["height_cm"] = height
    if "weight_kg" in payload:
        weight = _num(payload.get("weight_kg"))
        if weight is None or not (30 <= weight <= 300):
            raise HTTPException(400, "Вес должен быть от 30 до 300 кг")
        patch["weight_kg"] = weight
    if "target_weight_kg" in payload:
        raw = payload.get("target_weight_kg")
        if raw is None or raw == "":
            patch["target_weight_kg"] = None
        else:
            target = _num(raw)
            if target is None or not (30 <= target <= 300):
                raise HTTPException(400, "Целевой вес должен быть от 30 до 300 кг")
            patch["target_weight_kg"] = target
    if "enabled" in payload:
        patch["enabled"] = bool(payload.get("enabled"))
    return patch


@router.get("")
async def get_progress(request: Request):
    user = _user(request)
    _require_admin(user)
    data = progress_store.get(user["id"]) or {}
    return {
        "enabled": data.get("enabled", True),
        "progress": data or None,
        "metrics": _metrics(data),
        "disclaimer": (
            "BMI и диапазон веса — ориентир, а не диагноз и не медицинская "
            "рекомендация. Учитывайте состав тела, возраст, беременность, "
            "отёки и индивидуальные особенности. При сомнениях обратитесь к врачу."
        ),
    }


@router.post("")
async def save_progress(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    _require_admin(user)
    patch = _validate(payload)
    if not patch:
        raise HTTPException(400, "Нет данных для сохранения")
    data = await progress_store.upsert(user["id"], patch)
    return {
        "enabled": data.get("enabled", True),
        "progress": data,
        "metrics": _metrics(data),
    }
