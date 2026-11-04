from fastapi import APIRouter, Body, HTTPException, Request
from services.auth import get_current_user
from stores.settings import settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _require_admin(request: Request) -> None:
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")

@router.get("")
async def get_settings(request: Request):
    _require_admin(request)
    # Возвращаем только то, что можно менять в UI
    return {
        "generator_auto_active_time": settings_store.get("generator_auto_active_time", False),
        "generator_max_tokens": settings_store.get("generator_max_tokens", 15000),
        "gemini_poll_duration": settings_store.get("gemini_poll_duration", 300),
        "adapter_max_tokens": settings_store.get("adapter_max_tokens", 4000),
        "tts_enabled": settings_store.get("tts_enabled", False),
        "tts_daily_limit": settings_store.get("tts_daily_limit", 10),
        "telegram_bot_token": settings_store.get("telegram_bot_token", ""),
        "telegram_chat_id": settings_store.get("telegram_chat_id", "")
    }

@router.post("")
async def update_settings(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    if "generator_auto_active_time" in payload:
        await settings_store.set("generator_auto_active_time", bool(payload["generator_auto_active_time"]))
    if "generator_max_tokens" in payload:
        await settings_store.set("generator_max_tokens", int(payload["generator_max_tokens"]))
    if "gemini_poll_duration" in payload:
        await settings_store.set("gemini_poll_duration", float(payload["gemini_poll_duration"]))
    if "adapter_max_tokens" in payload:
        await settings_store.set("adapter_max_tokens", int(payload["adapter_max_tokens"]))
    if "tts_enabled" in payload:
        await settings_store.set("tts_enabled", bool(payload["tts_enabled"]))
    if "tts_daily_limit" in payload:
        await settings_store.set("tts_daily_limit", max(1, min(100, int(payload["tts_daily_limit"]))))

    if "telegram_bot_token" in payload or "telegram_chat_id" in payload:
        token = payload.get("telegram_bot_token", settings_store.get("telegram_bot_token", ""))
        cid = payload.get("telegram_chat_id", settings_store.get("telegram_chat_id", ""))
        await settings_store.set("telegram_bot_token", token)
        await settings_store.set("telegram_chat_id", cid)
        
        try:
            from services.telegram_service import telegram_service
        except ImportError:
            telegram_service = None
            print("[settings] Telegram disabled: aiogram is not installed")

        if telegram_service:
            await telegram_service.reload(token, cid)

    return {"status": "ok"}
