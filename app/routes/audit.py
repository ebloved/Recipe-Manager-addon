"""Админский API журнала действий."""
from fastapi import APIRouter, HTTPException, Query, Request

from services import audit
from services.auth import get_current_user

router = APIRouter(prefix="/api/admin/audit", tags=["audit"])


def _require_admin(request: Request) -> None:
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")


@router.get("")
async def list_audit(
    request: Request,
    q: str | None = Query(None),
    status: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _require_admin(request)
    return await audit.list_events(
        q=q,
        status=status,
        action=action,
        target_type=target_type,
        target_id=target_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/actions")
async def list_actions(request: Request):
    _require_admin(request)
    return {"items": await audit.list_actions()}


@router.get("/{event_id}")
async def get_event(event_id: str, request: Request):
    _require_admin(request)
    item = await audit.get_event(event_id)
    if not item:
        raise HTTPException(404, "Event not found")
    return {"item": item}
