"""Голосовой ввод: надиктованный текст → структура рецепта."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from services import audit, voice_recipe
from services.auth import get_current_user
from stores import recipe_store

router = APIRouter(tags=["voice"])


@router.post("/api/voice/recipe-parse")
async def parse_voice_recipe(request: Request, payload: dict = Body(...)):
    text = str(payload.get("text") or "").strip()
    if len(text) < 5:
        raise HTTPException(400, "Текст рецепта слишком короткий")
    if len(text) > 20000:
        raise HTTPException(413, "Текст рецепта слишком длинный")

    user = get_current_user(request)
    user_id = user.get("id") if user else "family"

    try:
        recipe, source, issues = await voice_recipe.parse(text, user_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"voice_parse_failed: {exc}") from exc

    saved = bool(payload.get("save"))
    if not saved:
        return {
            "recipe": recipe,
            "parse_source": source,
            "issues": issues,
            "saved": False,
        }

    recipe["owner_id"] = user_id
    recipe["owner_name"] = (user or {}).get("name") or "User"
    created = await recipe_store.add(recipe)

    try:
        from routes.recipes import _schedule_active_time
        from services.active_time import hash_instructions

        _schedule_active_time(
            created["id"],
            hash_instructions(created.get("instructions") or []),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[voice] active_time schedule failed: {exc}")

    try:
        actor = audit.actor_from_request(request)
        await audit.log_event(
            action="recipe.voice_save",
            label="Создание рецепта голосом",
            actor_kind=actor["kind"],
            actor_id=actor["id"],
            actor_name=actor["name"],
            actor_email=actor["email"],
            actor_role=actor["role"],
            target_type="recipe",
            target_id=created.get("id"),
            target_name=created.get("name"),
            status="ok",
            details={
                "parse_source": source,
                "ingredients": len(created.get("ingredients") or []),
                "steps": len(created.get("instructions") or []),
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[voice] audit log failed: {exc}")

    return {
        "recipe": created,
        "parse_source": source,
        "issues": issues,
        "saved": True,
    }
