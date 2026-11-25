"""Read-only API для внешних коннекторов: список покупок и план питания."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from services.api_auth import get_api_user
from services.export_items import build_export

router = APIRouter(prefix="/api/v1/export", tags=["export"])


@router.get("/shopping")
async def export_shopping(
    request: Request,
    source: str = "both",
    start: str | None = None,
    end: str | None = None,
    include_checked: bool = False,
    merge: bool = True,
    include_recipes: bool = True,
    include_pantry: bool = False,
    since: str | None = None,
):
    user = await get_api_user(request, scope="export")
    try:
        payload = build_export(
            user["id"],
            source=source,
            start=start,
            end=end,
            include_checked=include_checked,
            merge=merge,
            include_recipes=include_recipes,
            include_pantry=include_pantry,
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    etag = f'"{payload["revision"]}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, no-store",
        "X-Export-Revision": payload["revision"],
    }
    if (since and since.strip() == payload["revision"]) or (
        request.headers.get("if-none-match") == etag
    ):
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
