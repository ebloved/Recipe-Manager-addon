"""Gemini Live API: короткая PTT-сессия для готовки."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from config import GEMINI_API_KEY
from stores import recipe_store

MODEL = "gemini-2.5-flash-native-audio-latest"
_WS = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_TOKENS: dict[str, tuple[str, float]] = {}


def issue_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = (user_id, time.time() + 60)
    # Небольшая чистка, чтобы словарь не рос.
    now = time.time()
    for key, (_, exp) in list(_TOKENS.items()):
        if exp < now:
            _TOKENS.pop(key, None)
    return token


def consume_token(token: str) -> str | None:
    item = _TOKENS.pop(token or "", None)
    if not item:
        return None
    user_id, exp = item
    return user_id if exp >= time.time() else None


def _tools() -> list[dict[str, Any]]:
    return [{
        "functionDeclarations": [
            {"name": "next_step", "description": "Перейти к следующему шагу рецепта."},
            {"name": "previous_step", "description": "Вернуться к предыдущему шагу."},
            {"name": "repeat_step", "description": "Повторить текущий шаг."},
            {
                "name": "set_timer",
                "description": "Поставить кухонный таймер.",
                "parameters": {
                    "type": "object",
                    "properties": {"minutes": {"type": "number"}},
                    "required": ["minutes"],
                },
            },
        ]
    }]


def _prompt(recipe: dict[str, Any], step_index: int) -> str:
    steps = recipe.get("instructions") or []
    idx = max(0, min(step_index, len(steps) - 1)) if steps else 0
    current = steps[idx] if steps else "шагов нет"
    ings = []
    for ing in recipe.get("ingredients") or []:
        if isinstance(ing, dict):
            ings.append(" ".join(str(x) for x in (ing.get("amount"), ing.get("unit"), ing.get("name")) if x))
    return (
        "Ты — голосовой кулинарный ассистент. Отвечай по-русски кратко, "
        "только по делу, без чтения служебных инструкций.\n"
        f"Рецепт: {recipe.get('name') or ''}\n"
        f"Текущий шаг ({idx + 1}/{len(steps) or 1}): {current}\n"
        f"Ингредиенты: {', '.join(ings) or 'не указаны'}\n"
        "Если просят дальше/назад/повторить — вызови соответствующую функцию. "
        "Если просят таймер — вызови set_timer с минутами. "
        "После вызова функции коротко подтверди действие."
    )


async def run_live(ws: WebSocket, recipe: dict[str, Any], step_index: int) -> None:
    if not GEMINI_API_KEY:
        await ws.send_json({"type": "error", "message": "GEMINI_API_KEY не задан"})
        await ws.close(code=1011)
        return

    setup = {
        "setup": {
            "model": f"models/{MODEL}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": "Kore"}
                    }
                },
            },
            "systemInstruction": {"parts": [{"text": _prompt(recipe, step_index)}]},
            "tools": _tools(),
            "realtimeInputConfig": {
                "automaticActivityDetection": {"disabled": True}
            },
        }
    }
    uri = f"{_WS}?key={GEMINI_API_KEY}"
    try:
        async with websockets.connect(uri, max_size=None, open_timeout=20) as gem:
            await gem.send(json.dumps(setup))
            first = await asyncio.wait_for(gem.recv(), timeout=25)
            data = json.loads(first)
            if "setupComplete" not in data:
                await ws.send_json({"type": "error", "message": str(data)[:300]})
                await ws.close(code=1011)
                return
            await ws.send_json({"type": "live_ready"})

            async def browser_to_gemini() -> None:
                async for raw in ws.iter_text():
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    kind = msg.get("type")
                    if kind == "audio" and msg.get("data"):
                        await gem.send(json.dumps({
                            "realtimeInput": {
                                "mediaChunks": [{
                                    "mimeType": "audio/pcm;rate=16000",
                                    "data": msg["data"],
                                }]
                            }
                        }))
                    elif kind == "activity_start":
                        await gem.send(json.dumps({"realtimeInput": {"activityStart": {}}}))
                    elif kind == "activity_end":
                        await gem.send(json.dumps({"realtimeInput": {"activityEnd": {}}}))
                    elif kind == "close":
                        return

            async def gemini_to_browser() -> None:
                async for raw in gem:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "replace")
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        continue
                    tool = data.get("toolCall")
                    if tool:
                        responses = []
                        for call in tool.get("functionCalls") or []:
                            name = call.get("name") or ""
                            args = call.get("args") or {}
                            await ws.send_json({
                                "type": "action",
                                "action": name,
                                "args": args,
                            })
                            responses.append({
                                "id": call.get("id"),
                                "name": name,
                                "response": {"result": "ok"},
                            })
                        await gem.send(json.dumps({
                            "toolResponse": {"functionResponses": responses}
                        }))
                        continue
                    await ws.send_text(raw)

            tasks = [
                asyncio.create_task(browser_to_gemini()),
                asyncio.create_task(gemini_to_browser()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                try:
                    task.result()
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as exc:  # noqa: BLE001
                    print(f"[live] task error: {type(exc).__name__}: {exc}")
    except WebSocketDisconnect:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[live] error: {type(exc).__name__}: {exc}")
        try:
            await ws.send_json({"type": "error", "message": str(exc)[:300]})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
