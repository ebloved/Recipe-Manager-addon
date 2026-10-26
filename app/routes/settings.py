from fastapi import APIRouter, Body
from stores.settings import settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("")
async def get_settings():
    # Возвращаем только то, что можно менять в UI
    return {
        "generator_auto_active_time": settings_store.get("generator_auto_active_time", False),
        "generator_max_tokens": settings_store.get("generator_max_tokens", 15000),
        "gemini_poll_duration": settings_store.get("gemini_poll_duration", 300),
        "adapter_max_tokens": settings_store.get("adapter_max_tokens", 4000),
        "telegram_bot_token": settings_store.get("telegram_bot_token", ""),
        "telegram_chat_id": settings_store.get("telegram_chat_id", "")
    }

@router.post("")
async def update_settings(payload: dict = Body(...)):
    if "generator_auto_active_time" in payload:
        await settings_store.set("generator_auto_active_time", bool(payload["generator_auto_active_time"]))
    if "generator_max_tokens" in payload:
        await settings_store.set("generator_max_tokens", int(payload["generator_max_tokens"]))
    if "gemini_poll_duration" in payload:
        await settings_store.set("gemini_poll_duration", float(payload["gemini_poll_duration"]))
    if "adapter_max_tokens" in payload:
        await settings_store.set("adapter_max_tokens", int(payload["adapter_max_tokens"]))
        
    if "telegram_bot_token" in payload or "telegram_chat_id" in payload:
        token = payload.get("telegram_bot_token", settings_store.get("telegram_bot_token", ""))
        cid = payload.get("telegram_chat_id", settings_store.get("telegram_chat_id", ""))
        await settings_store.set("telegram_bot_token", token)
        await settings_store.set("telegram_chat_id", cid)
        
        from services.telegram_service import telegram_service
        await telegram_service.reload(token, cid)
        
    return {"status": "ok"}
