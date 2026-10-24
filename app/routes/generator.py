"""Эндпоинты генератора рецептов."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from config import (
    ADDON_VERSION,
    GEMINI_MODELS,
    GEMINI_PROXY,
    GENERATOR_DEFAULT_COUNT,
    GENERATOR_DEFAULT_SAMPLES,
    GENERATOR_MAX_COUNT,
    GENERATOR_SAMPLES_MAX,
)
from services.generator import (
    generate_suggestions,
    get_providers_status,
)
from stores import recipe_store, suggestions_store

router = APIRouter(prefix="/api/generator", tags=["generator"])


@router.post("/run")
async def run_generation(payload: dict[str, Any] = Body(...)):
    profile_id = payload.get("profile_id")
    topic = payload.get("topic")
    count = int(payload.get("count") or GENERATOR_DEFAULT_COUNT)
    samples_count = int(payload.get("samples_count") or GENERATOR_DEFAULT_SAMPLES)

    items = await generate_suggestions(
        profile_id=profile_id,
        topic=topic,
        count=count,
        samples_count=samples_count,
        max_count=GENERATOR_MAX_COUNT,
        samples_max=GENERATOR_SAMPLES_MAX,
    )
    await suggestions_store.add_many(items)
    return {"created": len(items), "suggestions": items}


@router.get("/suggestions")
async def list_suggestions(status: str | None = Query("pending")):
    items = suggestions_store.get_all(status=status)
    return {"suggestions": items, "count": len(items)}


@router.get("/suggestions/{sid}")
async def get_suggestion(sid: str):
    s = suggestions_store.get(sid)
    if not s:
        raise HTTPException(404, "Suggestion not found")
    return {"suggestion": s}


@router.post("/suggestions/{sid}/accept")
async def accept_suggestion(sid: str):
    s = suggestions_store.get(sid)
    if not s:
        raise HTTPException(404, "Suggestion not found")
    if s.get("status") == "accepted":
        raise HTTPException(409, "Already accepted")
    if s.get("error"):
        raise HTTPException(400, f"Cannot accept: {s['error']}")
    data = s.get("recipe_data")
    if not isinstance(data, dict):
        raise HTTPException(400, "Suggestion has no parsed recipe_data")

    data = {**data, "generated_by": "llm"}
    recipe = await recipe_store.add(data)
    await suggestions_store.update(sid, {"status": "accepted"})
    return {"recipe": recipe}


@router.delete("/suggestions/{sid}")
async def reject_suggestion(sid: str):
    ok = await suggestions_store.delete(sid)
    if not ok:
        raise HTTPException(404, "Suggestion not found")
    return {"deleted": True}


@router.get("/status")
async def generator_status():
    from services.generator.generator import get_last_attempt
    s = get_providers_status()
    s["version"] = ADDON_VERSION
    s["last_attempt"] = get_last_attempt()
    return s


@router.get("/diag")
async def generator_diag():
    """Диагностика без shell-доступа в контейнер."""
    from services.generator.generator import get_last_attempt
    try:
        from services.matcher.gemini_embedder import _GENERATE_TIMEOUT
        t = {"total_s": _GENERATE_TIMEOUT.read,
             "connect_s": _GENERATE_TIMEOUT.connect}
    except Exception as e:  # noqa: BLE001
        t = {"error": str(e)}
    return {
        "addon_version": ADDON_VERSION,
        "gemini_models": GEMINI_MODELS,
        "gemini_proxy_set": bool(GEMINI_PROXY),
        "complete_timeout": t,
        "default_count": GENERATOR_DEFAULT_COUNT,
        "default_samples": GENERATOR_DEFAULT_SAMPLES,
        "max_count": GENERATOR_MAX_COUNT,
        "samples_max": GENERATOR_SAMPLES_MAX,
        "last_attempt": get_last_attempt(),
        "nginx_hint": "HA ingress cuts at ~60s; keep Gemini call <50s",
    }
