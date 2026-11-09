"""API генерации меню на неделю."""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from services.meal_plan_access import require_access
from services.meal_plan_generator import (
    ALLOWED_MEALS,
    MAX_NEW_DEFAULT,
    _recipe_summary,
    run_plan_generation,
    run_replacement,
)
from services.shopping_from_recipe import add_recipe_id_to_shopping
from stores import (
    gen_profiles_store,
    jobs_store,
    meal_plan_drafts_store,
    meal_plan_store,
    recipe_store,
    suggestions_store,
)

router = APIRouter(prefix="/api/meal-plan", tags=["meal-plan-gen"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_week_start() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return (monday + timedelta(days=7)).isoformat()


def _require_user(request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Unauthorized")
    return user


async def _profile(
    profile_id: str | None,
    user_id: str | None,
) -> dict[str, Any] | None:
    if profile_id:
        profile = gen_profiles_store.get(profile_id)
        if (
            not profile
            or profile.get("deleted")
            or (
                profile.get("owner_id")
                and profile.get("owner_id") != user_id
            )
        ):
            raise HTTPException(404, "Profile not found")
        return profile
    if user_id:
        from stores.user_active_profiles import user_active_profiles

        exists, per_user_id = await user_active_profiles.get_with_presence(user_id)
        if exists:
            if not per_user_id:
                return None
            profile = gen_profiles_store.get(per_user_id)
            return profile if profile and not profile.get("deleted") else None
    fallback = gen_profiles_store.get_active()
    if (
        fallback
        and user_id
        and fallback.get("owner_id")
        and fallback.get("owner_id") != user_id
    ):
        return None
    return fallback


def _draft_for(user: dict[str, Any], draft_id: str) -> dict[str, Any]:
    draft = meal_plan_drafts_store.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.get("owner_id") != user.get("id") and user.get("role") != "admin":
        raise HTTPException(404, "Draft not found")
    return draft


async def _reconcile_draft(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    """Чинит черновик, зависший после перезапуска аддона."""
    if not draft or draft.get("status") != "generating":
        return draft
    job = jobs_store.get(str(draft.get("job_id") or ""))
    if not job:
        return await meal_plan_drafts_store.update(draft["id"], {
            "status": "error",
            "error": "Генерация прервана перезапуском. Запустите заново.",
            "progress": {"stage": "Ошибка", "done": 0, "total": 1},
        })
    if job.get("status") == "error":
        return await meal_plan_drafts_store.update(draft["id"], {
            "status": "error",
            "error": job.get("error") or "Генерация не удалась",
            "progress": {"stage": "Ошибка", "done": 0, "total": 1},
        })
    if job.get("status") == "done":
        return await meal_plan_drafts_store.update(draft["id"], {
            "status": "ready",
            "progress": {"stage": "Готово", "done": 1, "total": 1},
        })
    return draft


def _draft_view(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    if not draft:
        return None
    out = copy.deepcopy(draft)
    pending = 0
    has_recipe = False
    for slot in out.get("slots") or []:
        rid = slot.get("recipe_id")
        if rid and not slot.get("recipe"):
            slot["recipe"] = _recipe_summary(recipe_store.get(str(rid)))
        side_id = slot.get("side_recipe_id")
        if side_id and not slot.get("side_recipe"):
            slot["side_recipe"] = _recipe_summary(recipe_store.get(str(side_id)))
        if rid and slot.get("source") != "existing":
            has_recipe = True
        sid = slot.get("suggestion_id")
        if sid:
            suggestion = suggestions_store.get(str(sid))
            slot["suggestion"] = suggestion
            if suggestion and suggestion.get("status") == "pending":
                pending += 1
        else:
            slot["suggestion"] = None
    out["pending_count"] = pending
    out["can_save"] = pending == 0 and has_recipe
    return out


async def _run_generate_job(
    *,
    draft_id: str,
    job_id: str,
    user_id: str,
    profile: dict[str, Any] | None,
    week_start: str,
    meals: list[str],
    servings: float,
    user_prompt: str | None,
    max_new: int,
) -> None:
    try:
        created = await run_plan_generation(
            draft_id=draft_id,
            job_id=job_id,
            user_id=user_id,
            profile=profile,
            week_start=week_start,
            meals=meals,
            servings=servings,
            user_prompt=user_prompt,
            max_new=max_new,
        )
        await jobs_store.update(
            job_id, status="done", created=created, finished_at=_now()
        )
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        await meal_plan_drafts_store.update(draft_id, {
            "status": "error",
            "error": message,
            "progress": {"stage": "Ошибка", "done": 0, "total": 1},
        })
        await jobs_store.update(
            job_id, status="error", error=message, finished_at=_now()
        )
        print(f"[meal-plan-gen] job {job_id} failed: {message}")


async def _run_replace_job(
    *,
    draft_id: str,
    job_id: str,
    user_id: str,
    profile: dict[str, Any] | None,
    slot_date: str,
    slot_meal: str,
    servings: float,
    user_prompt: str | None,
) -> None:
    try:
        created = await run_replacement(
            draft_id=draft_id,
            job_id=job_id,
            user_id=user_id,
            profile=profile,
            slot_date=slot_date,
            slot_meal=slot_meal,
            servings=servings,
            user_prompt=user_prompt,
        )
        await jobs_store.update(
            job_id, status="done", created=created, finished_at=_now()
        )
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        draft = meal_plan_drafts_store.get(draft_id)
        if draft:
            warnings = list(draft.get("warnings") or [])
            warnings.append(
                f"Замена для {slot_meal} {slot_date}: {message}"
            )
            await meal_plan_drafts_store.update(draft_id, {
                "status": "ready",
                "warnings": warnings,
                "progress": {"stage": "Замена не удалась", "done": 0, "total": 1},
            })
        await jobs_store.update(
            job_id, status="error", error=message, finished_at=_now()
        )


@router.get("/drafts")
async def list_drafts(request: Request, active: int = 0):
    user = _require_user(request)
    require_access(user)
    if active:
        draft = meal_plan_drafts_store.latest_active(user["id"])
        draft = await _reconcile_draft(draft)
        return {"draft": _draft_view(draft)}
    items = meal_plan_drafts_store.list_for_owner(user["id"], limit=20)
    items = [await _reconcile_draft(item) for item in items]
    return {"drafts": [_draft_view(item) for item in items]}


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str, request: Request):
    user = _require_user(request)
    require_access(user)
    draft = _draft_for(user, draft_id)
    draft = await _reconcile_draft(draft)
    return {"draft": _draft_view(draft)}


@router.post("/generate")
async def generate_meal_plan(request: Request, payload: dict[str, Any] = Body(...)):
    user = _require_user(request)
    require_access(user)

    active = meal_plan_drafts_store.latest_active(user["id"])
    active = await _reconcile_draft(active)
    if active and active.get("status") == "generating":
        raise HTTPException(409, "Генерация уже идёт")

    week_start = str(payload.get("week_start") or "").strip() or _default_week_start()
    try:
        date.fromisoformat(week_start)
    except ValueError as exc:
        raise HTTPException(400, "Invalid week_start") from exc

    meals_raw = payload.get("meals")
    if not isinstance(meals_raw, list) or not meals_raw:
        meals_raw = ["breakfast", "lunch", "dinner"]
    meals = [meal for meal in ALLOWED_MEALS if meal in set(map(str, meals_raw))]
    if not meals:
        raise HTTPException(400, "Выберите хотя бы один приём пищи")

    try:
        servings = float(payload.get("servings") or 2)
    except (TypeError, ValueError):
        servings = 2
    servings = max(1.0, min(20.0, servings))

    user_prompt = str(payload.get("prompt") or "").strip()[:400] or None
    raw_max_new = payload.get("max_new")
    if raw_max_new is None:
        max_new = MAX_NEW_DEFAULT
    else:
        try:
            max_new = int(raw_max_new)
        except (TypeError, ValueError):
            max_new = MAX_NEW_DEFAULT
    max_new = max(0, min(MAX_NEW_DEFAULT, max_new))

    profile = await _profile(
        str(payload.get("profile_id") or "") or None,
        user["id"],
    )
    draft = await meal_plan_drafts_store.add({
        "owner_id": user["id"],
        "week_start": week_start,
        "meals": meals,
        "servings": servings,
        "profile_id": (profile or {}).get("id"),
        "profile_name": (profile or {}).get("name"),
        "prompt": user_prompt,
        "max_new": max_new,
        "status": "generating",
        "slots": [],
        "warnings": [],
        "generated_count": 0,
        "progress": {"stage": "Старт", "done": 0, "total": 1},
    })
    job = await jobs_store.create({
        "kind": "meal_plan",
        "mode": "generate",
        "draft_id": draft["id"],
        "week_start": week_start,
        "meals": meals,
        "user_id": user["id"],
    }, user_id=user["id"])
    draft = await meal_plan_drafts_store.update(draft["id"], {"job_id": job["id"]})

    asyncio.create_task(_run_generate_job(
        draft_id=draft["id"],
        job_id=job["id"],
        user_id=user["id"],
        profile=profile,
        week_start=week_start,
        meals=meals,
        servings=servings,
        user_prompt=user_prompt,
        max_new=max_new,
    ))
    return {
        "draft_id": draft["id"],
        "job_id": job["id"],
        "draft": _draft_view(draft),
    }


@router.post("/drafts/{draft_id}/approve")
async def approve_suggestion(
    draft_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = _require_user(request)
    require_access(user)
    draft = _draft_for(user, draft_id)
    suggestion_id = str(payload.get("suggestion_id") or "").strip()
    if not suggestion_id:
        raise HTTPException(400, "suggestion_id is required")

    slot = next(
        (s for s in draft.get("slots") or [] if s.get("suggestion_id") == suggestion_id),
        None,
    )
    if not slot:
        raise HTTPException(404, "Slot not found")

    if slot.get("recipe_id"):
        return {"draft": _draft_view(draft), "recipe": recipe_store.get(slot["recipe_id"])}

    suggestion = suggestions_store.get(suggestion_id)
    if (
        not suggestion
        or suggestion.get("origin") != "meal_plan"
        or suggestion.get("draft_id") != draft_id
    ):
        raise HTTPException(404, "Suggestion not found")
    if suggestion.get("error"):
        raise HTTPException(400, f"Рецепт не распознан: {suggestion['error']}")

    accepted_id = suggestion.get("accepted_recipe_id")
    if accepted_id:
        existing = recipe_store.get(str(accepted_id))
        if existing:
            slot.update({
                "recipe_id": existing.get("id"),
                "recipe": _recipe_summary(existing),
                "suggestion_id": None,
                "approved": True,
                "source": "generated",
            })
            await meal_plan_drafts_store.update(
                draft_id, {"slots": draft.get("slots") or []}
            )
            return {
                "recipe": existing,
                "draft": _draft_view(meal_plan_drafts_store.get(draft_id)),
            }

    recipe_data = suggestion.get("recipe_data")
    if not isinstance(recipe_data, dict):
        raise HTTPException(400, "Suggestion has no parsed recipe_data")

    data = {
        **recipe_data,
        "generated_by": "llm",
        "generation": {
            "origin": "meal_plan",
            "draft_id": draft_id,
            "job_id": draft.get("job_id"),
            "provider": suggestion.get("provider"),
        },
    }
    for key in (
        "id", "owner_id", "personal_of", "personal_selected", "share_token",
        "version", "revision", "hidden_by", "parent_id", "adapted_versions",
        "created_at", "updated_at",
    ):
        data.pop(key, None)
    recipe = await recipe_store.add(data)

    await suggestions_store.update(suggestion_id, {
        "status": "accepted",
        "accepted_recipe_id": recipe.get("id"),
    })
    slot.update({
        "recipe_id": recipe.get("id"),
        "recipe": _recipe_summary(recipe),
        "suggestion_id": None,
        "approved": True,
        "source": "generated",
    })
    await meal_plan_drafts_store.update(draft_id, {"slots": draft.get("slots") or []})
    return {
        "recipe": recipe,
        "draft": _draft_view(meal_plan_drafts_store.get(draft_id)),
    }


@router.post("/drafts/{draft_id}/reject")
async def reject_suggestion(
    draft_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = _require_user(request)
    require_access(user)
    draft = _draft_for(user, draft_id)
    suggestion_id = str(payload.get("suggestion_id") or "").strip()
    if not suggestion_id:
        raise HTTPException(400, "suggestion_id is required")

    slot = next(
        (s for s in draft.get("slots") or [] if s.get("suggestion_id") == suggestion_id),
        None,
    )
    if not slot:
        raise HTTPException(404, "Slot not found")

    await suggestions_store.delete(suggestion_id)
    slot.update({
        "suggestion_id": None,
        "suggestion": None,
        "source": "empty",
        "approved": False,
        "recipe_id": None,
        "recipe": None,
        "side_recipe_id": None,
        "side_recipe": None,
        "needs_side": False,
    })
    await meal_plan_drafts_store.update(draft_id, {"slots": draft.get("slots") or []})
    return {"draft": _draft_view(meal_plan_drafts_store.get(draft_id))}


@router.post("/drafts/{draft_id}/replace")
async def replace_slot(
    draft_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = _require_user(request)
    require_access(user)
    draft = _draft_for(user, draft_id)
    if draft.get("status") == "generating":
        raise HTTPException(409, "Генерация уже идёт")
    if draft.get("status") == "saved":
        raise HTTPException(409, "План уже сохранён")

    slot_date = str(payload.get("date") or "").strip()
    slot_meal = str(payload.get("meal_type") or "").strip()
    if slot_meal not in ALLOWED_MEALS:
        raise HTTPException(400, "Invalid meal_type")
    slot = next(
        (
            s for s in draft.get("slots") or []
            if s.get("date") == slot_date and s.get("meal_type") == slot_meal
        ),
        None,
    )
    if not slot:
        raise HTTPException(404, "Slot not found")
    if slot.get("recipe_id"):
        raise HTTPException(400, "В этом слоте уже есть рецепт")

    previous_sid = slot.get("suggestion_id")
    if previous_sid:
        await suggestions_store.delete(str(previous_sid))
    slot.update({
        "suggestion_id": None,
        "suggestion": None,
        "source": "empty",
        "approved": False,
        "recipe_id": None,
        "recipe": None,
        "side_recipe_id": None,
        "side_recipe": None,
        "needs_side": False,
    })

    profile = None
    if draft.get("profile_id"):
        profile = gen_profiles_store.get(draft["profile_id"])
    job = await jobs_store.create({
        "kind": "meal_plan",
        "mode": "replace",
        "draft_id": draft_id,
        "slot_date": slot_date,
        "slot_meal": slot_meal,
        "user_id": user["id"],
    }, user_id=user["id"])
    await meal_plan_drafts_store.update(draft_id, {
        "status": "generating",
        "slots": draft.get("slots") or [],
        "job_id": job["id"],
        "progress": {"stage": "Генерируем замену", "done": 0, "total": 1},
    })
    asyncio.create_task(_run_replace_job(
        draft_id=draft_id,
        job_id=job["id"],
        user_id=user["id"],
        profile=profile,
        slot_date=slot_date,
        slot_meal=slot_meal,
        servings=float(draft.get("servings") or 2),
        user_prompt=draft.get("prompt"),
    ))
    return {"job_id": job["id"], "draft": _draft_view(meal_plan_drafts_store.get(draft_id))}


@router.post("/drafts/{draft_id}/save")
async def save_draft(
    draft_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = _require_user(request)
    require_access(user)
    draft = _draft_for(user, draft_id)
    if draft.get("status") == "generating":
        raise HTTPException(409, "Дождитесь окончания генерации")
    if draft.get("status") == "saved":
        raise HTTPException(409, "План уже сохранён")

    slots = draft.get("slots") or []
    pending = [
        s for s in slots
        if s.get("suggestion_id")
        and (suggestions_store.get(str(s["suggestion_id"])) or {}).get("status") == "pending"
    ]
    if pending:
        raise HTTPException(409, f"Есть неодобренные рецепты: {len(pending)}")

    week_start = str(draft.get("week_start"))
    start = date.fromisoformat(week_start)
    end = (start + timedelta(days=6)).isoformat()
    existing = meal_plan_store.get_range(week_start, end)
    occupied = {
        (str(e.get("date")), str(e.get("meal_type")))
        for e in existing
    }

    new_entries: list[dict[str, Any]] = []
    skipped = 0
    added_slots: list[dict[str, Any]] = []
    for slot in slots:
        recipe_id = slot.get("recipe_id")
        if not recipe_id:
            continue
        if slot.get("source") == "existing" or slot.get("locked"):
            continue
        key = (str(slot.get("date")), str(slot.get("meal_type")))
        if key in occupied:
            skipped += 1
            continue
        base_entry = {
            "date": slot.get("date"),
            "meal_type": slot.get("meal_type"),
            "servings": slot.get("servings"),
            "notes": None,
            "source": "generated",
            "draft_id": draft_id,
            "job_id": draft.get("job_id"),
        }
        new_entries.append({**base_entry, "recipe_id": recipe_id})
        side_id = slot.get("side_recipe_id")
        if side_id:
            new_entries.append({
                **base_entry,
                "recipe_id": side_id,
                "source": "generated_side",
                "side_for": recipe_id,
            })
        occupied.add(key)
        added_slots.append(slot)

    if not new_entries and not skipped:
        raise HTTPException(400, "В плане нет рецептов для сохранения")

    try:
        await meal_plan_store.add_many(new_entries, owner_id="family")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            500, f"Не удалось сохранить план: {type(exc).__name__}: {exc}"
        ) from exc
    saved_slots = len(added_slots)
    added = len(new_entries)

    shopping = {"added": 0, "merged": 0, "total": 0}
    if payload.get("add_to_shopping"):
        for slot in added_slots:
            desired = float(slot.get("servings") or 1)
            for rid in (slot.get("recipe_id"), slot.get("side_recipe_id")):
                if not rid:
                    continue
                try:
                    recipe = recipe_store.get(str(rid)) or {}
                    try:
                        recipe_yield = float(recipe.get("servings") or 1)
                    except (TypeError, ValueError):
                        recipe_yield = 1.0
                    if recipe_yield <= 0:
                        recipe_yield = 1.0
                    # Ингредиенты в рецепте — на его выход (recipe.servings).
                    # Нужно масштабировать к запланированному числу порций.
                    multiplier = desired / recipe_yield
                    result = await add_recipe_id_to_shopping(
                        str(rid),
                        owner_id=user["id"],
                        multiplier=multiplier,
                    )
                    for key in ("added", "merged", "total"):
                        shopping[key] += int(result.get(key, 0))
                except Exception as exc:  # noqa: BLE001
                    print(f"[meal-plan-gen] shopping failed: {exc}")

    updated = await meal_plan_drafts_store.update(draft_id, {
        "status": "saved",
        "saved_count": added,
        "saved_slots": saved_slots,
        "skipped_existing": skipped,
        "shopping": shopping,
        "saved_at": _now(),
        "slots": slots,
    })
    return {
        "saved": added,
        "saved_slots": saved_slots,
        "skipped_existing": skipped,
        "shopping": shopping,
        "draft": _draft_view(updated),
    }


@router.delete("/drafts/{draft_id}")
async def discard_draft(draft_id: str, request: Request):
    user = _require_user(request)
    require_access(user)
    draft = _draft_for(user, draft_id)
    if draft.get("status") == "generating":
        raise HTTPException(409, "Дождитесь окончания генерации")
    for suggestion in suggestions_store.get_for_draft(draft_id):
        if suggestion.get("status") == "pending":
            await suggestions_store.delete(suggestion["id"])
    updated = await meal_plan_drafts_store.update(draft_id, {
        "status": "discarded",
        "slots": [],
        "progress": {"stage": "Отменено", "done": 0, "total": 0},
    })
    return {"discarded": True, "draft": _draft_view(updated)}
