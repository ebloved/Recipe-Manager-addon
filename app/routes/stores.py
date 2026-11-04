"""Магазины: OAuth-подключение и статус (per-user)."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from integrations.stores.vkusvill import oauth as vv_oauth
from integrations.stores.vkusvill.cart import build_cart
from integrations.stores.vkusvill.client import products_search
from integrations.stores.vkusvill.mcp_client import MCPError
from services.auth import get_current_user
from stores.store_credentials import store_credentials

router = APIRouter(prefix="/api/stores", tags=["stores"])

SUPPORTED_STORES = {
    "vkusvill": {
        "id": "vkusvill",
        "name": "ВкусВилл",
        "auth_type": "oauth2_pkce",
    },
}


def _user_or_401(request: Request) -> dict:
    user = get_current_user(request)
    if not user or not user.get("id"):
        raise HTTPException(401, "Unauthorized")
    return user


@router.get("")
async def list_stores(request: Request):
    user = _user_or_401(request)
    owner_id = user["id"]
    stores = []
    for store_id, meta in SUPPORTED_STORES.items():
        connected = await store_credentials.is_connected(owner_id, store_id)
        creds = await store_credentials.get(owner_id, store_id) if connected else None
        configured = vv_oauth.is_configured() if store_id == "vkusvill" else False
        stores.append({
            **meta,
            "configured": configured,
            "connected": connected,
            "expires_at": (
                creds["expires_at"].isoformat()
                if creds and creds.get("expires_at") else None
            ),
            "scopes": (creds or {}).get("scopes"),
        })
    return {"stores": stores}


@router.get("/{store_id}/oauth/start")
async def oauth_start(store_id: str, request: Request):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    if store_id != "vkusvill":
        raise HTTPException(400, "OAuth is not supported for this store")
    try:
        url = await vv_oauth.create_authorization_url(user["id"], store_id)
    except vv_oauth.StoreOAuthError as exc:
        raise HTTPException(503, str(exc)) from exc
    return RedirectResponse(url=url, status_code=302)


@router.get("/{store_id}/callback")
async def oauth_callback(store_id: str, request: Request):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")

    error = request.query_params.get("error")
    if error:
        msg = request.query_params.get("error_description") or error
        return RedirectResponse(
            url=f"/?store_status=error&store_id={store_id}&message={quote(msg)}",
            status_code=302,
        )

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return RedirectResponse(
            url=f"/?store_status=error&store_id={store_id}&message=missing_code_or_state",
            status_code=302,
        )

    try:
        await vv_oauth.exchange_code(state, code, user["id"])
    except vv_oauth.StoreOAuthError as exc:
        return RedirectResponse(
            url=f"/?store_status=error&store_id={store_id}&message={quote(str(exc))}",
            status_code=302,
        )
    return RedirectResponse(
        url=f"/?store_status=connected&store_id={store_id}",
        status_code=302,
    )


@router.get("/{store_id}/oauth/callback", include_in_schema=False)
async def oauth_callback_alias(store_id: str, request: Request):
    """Совместимость со старым redirect URI (/oauth/callback)."""
    return await oauth_callback(store_id, request)


@router.post("/{store_id}/disconnect")
async def disconnect(store_id: str, request: Request):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    if store_id == "vkusvill":
        await vv_oauth.revoke(user["id"], store_id)
    else:
        await store_credentials.delete(user["id"], store_id)
    return {"status": "ok", "connected": False}


@router.post("/{store_id}/test")
async def test_store(store_id: str, request: Request):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    if store_id == "vkusvill":
        try:
            token = await vv_oauth.get_valid_access_token(user["id"], store_id)
            products = await products_search("молоко", limit=1, token=token)
        except vv_oauth.StoreNotConnected as exc:
            raise HTTPException(400, str(exc)) from exc
        except MCPError as exc:
            raise HTTPException(502, f"MCP error: {exc}") from exc
        return {
            "ok": True,
            "store_id": store_id,
            "token_present": bool(token),
            "mcp_products": len(products),
            "sample": products[0].name if products else None,
            "message": "OAuth и MCP работают.",
        }
    return {"ok": True, "store_id": store_id}


@router.post("/{store_id}/cart")
async def build_store_cart(store_id: str, request: Request):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    if store_id != "vkusvill":
        raise HTTPException(400, "Cart building is not supported for this store")

    try:
        result = await build_cart(
            owner_id=user["id"],
            user_id=user["id"],
            store_id=store_id,
            user=user,
        )
    except vv_oauth.StoreNotConnected as exc:
        raise HTTPException(400, str(exc)) from exc
    except vv_oauth.StoreOAuthError as exc:
        raise HTTPException(502, f"VkusVill OAuth error: {exc}") from exc
    except MCPError as exc:
        raise HTTPException(502, f"VkusVill MCP error: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return result
