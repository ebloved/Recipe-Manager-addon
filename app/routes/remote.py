"""Локальные endpoint'ы BFF для подключения к серверу."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from services.auth import get_current_user
from services import remote_cache, remote_client

router = APIRouter(prefix="/api/remote", tags=["remote"])


def _require_admin(request: Request) -> None:
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")


@router.get("/status")
async def remote_status(request: Request):
    _require_admin(request)
    data = {**remote_client.status(), **remote_cache.status()}
    data["online"] = await remote_client.ping() if data.get("paired") else False
    return data


@router.post("/pair/init")
async def remote_pair_init(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    server_url = str(payload.get("server_url") or "").strip()
    return await remote_client.pair_init(server_url, payload.get("device_id"))


@router.post("/pair/poll")
async def remote_pair_poll(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    server_url = str(payload.get("server_url") or "").strip()
    device_code = str(payload.get("device_code") or "").strip()
    if not device_code:
        raise HTTPException(400, "device_code is required")
    data = await remote_client.pair_poll(server_url, device_code)
    if data.get("status") == "approved":
        try:
            await remote_cache.sync_all()
        except Exception as exc:  # noqa: BLE001
            print(f"[remote] initial sync failed: {exc}")
    return data


@router.post("/sync")
async def remote_sync(request: Request):
    _require_admin(request)
    return await remote_cache.sync_all()


@router.post("/disconnect")
async def remote_disconnect(request: Request):
    _require_admin(request)
    remote_client.clear_token()
    return {"status": "ok", "paired": False}
