from fastapi import APIRouter, Body
from stores.settings import settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("")
async def get_settings():
    # Возвращаем только то, что можно менять в UI
    return {
        "generator_auto_active_time": settings_store.get("generator_auto_active_time", False)
    }

@router.post("")
async def update_settings(payload: dict = Body(...)):
    if "generator_auto_active_time" in payload:
        await settings_store.set("generator_auto_active_time", bool(payload["generator_auto_active_time"]))
    return {"status": "ok"}
