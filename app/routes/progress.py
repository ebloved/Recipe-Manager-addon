"""Личный прогресс: рост, вес, цель, журнал и BMI-ориентир.

Данные доступны только владельцу. Это не медицинская рекомендация.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from stores.progress import progress_store

router = APIRouter(prefix="/api/progress", tags=["progress"])


def _user(request: Request) -> dict[str, Any] | None:
    return get_current_user(request)


def _require_user(user: dict[str, Any] | None) -> None:
    if not user:
        raise HTTPException(401, "Unauthorized")


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
    age = _num(data.get("age"))
    sex = str(data.get("sex") or "")
    activity = str(data.get("activity") or "")
    tdee = None
    if age and sex in ("male", "female") and activity in ("low", "medium", "high"):
        bmr = 10 * weight + 6.25 * height - 5 * age + (5 if sex == "male" else -161)
        factor = {"low": 1.2, "medium": 1.375, "high": 1.55}[activity]
        tdee = round(bmr * factor)
    return {
        "age": age,
        "sex": sex or None,
        "activity": activity or None,
        "tdee": tdee,
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
    if "age" in payload:
        raw = payload.get("age")
        if raw is None or raw == "":
            patch["age"] = None
        else:
            age = _num(raw)
            if age is None or not (10 <= age <= 120):
                raise HTTPException(400, "Возраст должен быть от 10 до 120 лет")
            patch["age"] = int(age)
    if "sex" in payload:
        value = str(payload.get("sex") or "").strip().lower()
        if value not in ("", "male", "female"):
            raise HTTPException(400, "Некорректный пол")
        patch["sex"] = value or None
    if "activity" in payload:
        value = str(payload.get("activity") or "").strip().lower()
        if value not in ("", "low", "medium", "high"):
            raise HTTPException(400, "Некорректная активность")
        patch["activity"] = value or None
    if "enabled" in payload:
        patch["enabled"] = bool(payload.get("enabled"))
    return patch


@router.get("")
async def get_progress(request: Request):
    user = _user(request)
    _require_user(user)
    data = progress_store.get(user["id"]) or {}
    weights = sorted(
        [dict(item) for item in (data.get("weights") or [])],
        key=lambda item: str(item.get("date") or ""),
    )
    food = sorted(
        [dict(item) for item in (data.get("food") or [])],
        key=lambda item: str(item.get("date") or ""),
    )
    return {
        "enabled": data.get("enabled", True),
        "progress": data or None,
        "metrics": _metrics(data),
        "weights": weights,
        "food": food,
        "disclaimer": (
            "BMI и диапазон веса — ориентир, а не диагноз и не медицинская "
            "рекомендация. Учитывайте состав тела, возраст, беременность, "
            "отёки и индивидуальные особенности. При сомнениях обратитесь к врачу."
        ),
    }


@router.post("/food")
async def add_food(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    _require_user(user)
    date_value = str(payload.get("date") or "").strip()
    try:
        date_type.fromisoformat(date_value)
    except ValueError as exc:
        raise HTTPException(400, "Некорректная дата") from exc
    if date_value > date_type.today().isoformat():
        raise HTTPException(400, "Дата не может быть в будущем")
    raw_calories = payload.get("calories")
    calories = _num(raw_calories) if raw_calories not in (None, "") else None
    if calories is not None and not (0 <= calories <= 10000):
        raise HTTPException(400, "Калории должны быть от 0 до 10000")
    note = str(payload.get("note") or "").strip()[:500] or None
    food = await progress_store.add_food(
        user["id"],
        date=date_value,
        calories=calories,
        note=note,
        outside=bool(payload.get("outside")),
    )
    return {"food": food}


@router.delete("/food/{entry_id}")
async def delete_food(entry_id: str, request: Request):
    user = _user(request)
    _require_user(user)
    food = await progress_store.delete_food(user["id"], entry_id)
    if food is None:
        raise HTTPException(404, "Запись не найдена")
    return {"food": food}


@router.post("/weights")
async def add_weight(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    _require_user(user)
    date_value = str(payload.get("date") or "").strip()
    try:
        date_type.fromisoformat(date_value)
    except ValueError as exc:
        raise HTTPException(400, "Некорректная дата") from exc
    if date_value > date_type.today().isoformat():
        raise HTTPException(400, "Дата не может быть в будущем")
    weight = _num(payload.get("weight_kg"))
    if weight is None or not (30 <= weight <= 300):
        raise HTTPException(400, "Вес должен быть от 30 до 300 кг")
    note = str(payload.get("note") or "").strip()[:200] or None
    weights = await progress_store.add_weight(
        user["id"], date=date_value, weight_kg=weight, note=note
    )
    return {"weights": weights}


@router.delete("/weights/{entry_id}")
async def delete_weight(entry_id: str, request: Request):
    user = _user(request)
    _require_user(user)
    weights = await progress_store.delete_weight(user["id"], entry_id)
    if weights is None:
        raise HTTPException(404, "Запись не найдена")
    return {"weights": weights}


@router.delete("")
async def reset_progress(request: Request):
    user = _user(request)
    _require_user(user)
    deleted = await progress_store.delete(user["id"])
    return {"deleted": deleted}


@router.post("")
async def save_progress(request: Request, payload: dict[str, Any] = Body(...)):
    user = _user(request)
    _require_user(user)
    patch = _validate(payload)
    if not patch:
        raise HTTPException(400, "Нет данных для сохранения")
    data = await progress_store.upsert(user["id"], patch)
    return {
        "enabled": data.get("enabled", True),
        "progress": data,
        "metrics": _metrics(data),
    }
