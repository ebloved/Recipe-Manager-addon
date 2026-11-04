"""Серверная озвучка PTT через Gemini TTS."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, Response

from services.auth import get_current_user
from services import step_audio, voice_tts, voice_live
from stores import recipe_store

router = APIRouter(tags=["voice"])


@router.post("/api/voice/tts")
async def tts(request: Request, payload: dict = Body(...)):
    if not get_current_user(request):
        raise HTTPException(401, "Unauthorized")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > 500:
        raise HTTPException(400, "text is too long")
    try:
        audio = await voice_tts.synthesize(text)
    except voice_tts.TTSError as exc:
        raise HTTPException(503, f"TTS unavailable: {exc}") from exc
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/api/voice/live-token")
async def live_token(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Unauthorized")
    return {"token": voice_live.issue_token(user["id"]), "expires_in": 60}


@router.websocket("/ws/cooking/live")
async def live_socket(websocket: WebSocket, token: str = "", recipe_id: str = "", step: int = 0):
    if not voice_live.consume_token(token):
        await websocket.close(code=1008)
        return
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await voice_live.run_live(websocket, recipe, step)


@router.get("/api/voice/audio/{audio_hash}.mp3")
async def step_audio_file(request: Request, audio_hash: str):
    if not get_current_user(request):
        raise HTTPException(401, "Unauthorized")
    path = step_audio.audio_path(audio_hash)
    if path is None:
        raise HTTPException(404, "Not found")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/api/recipes/{recipe_id}/step-audio")
async def list_step_audio(recipe_id: str, request: Request):
    if not get_current_user(request):
        raise HTTPException(401, "Unauthorized")
    return {"items": await step_audio.list_for_recipe(recipe_id)}


@router.post("/api/recipes/{recipe_id}/step-audio/{index}")
async def generate_step_audio(recipe_id: str, index: int, request: Request):
    if not get_current_user(request):
        raise HTTPException(401, "Unauthorized")
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    try:
        item = await step_audio.get_or_create(recipe, index)
    except step_audio.StepAudioError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"item": item, "usage": step_audio.usage()}
