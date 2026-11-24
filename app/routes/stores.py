"""Магазины: OAuth-подключение и статус (per-user)."""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import RedirectResponse

from integrations.stores.vkusvill import oauth as vv_oauth
from integrations.stores.vkusvill.cart import build_cart
from integrations.stores.vkusvill.client import products_search
from integrations.stores.vkusvill.mcp_client import MCPError
from integrations.stores.lenta import cart as lenta_cart
from integrations.stores.lenta.client import (
    products_search as lenta_products_search,
    resolve_store as lenta_resolve_store,
)
from integrations.stores.lenta.mcp_client import MCPError as LentaMCPError
from integrations.stores.auchan import links as auchan_links
from integrations.stores.auchan.client import auchan_client, AuchanAPIError
from services.auth import get_current_user
from stores.store_credentials import store_credentials
from stores.store_settings import store_settings

router = APIRouter(prefix="/api/stores", tags=["stores"])

SUPPORTED_STORES = {
    "vkusvill": {
        "id": "vkusvill",
        "name": "ВкусВилл",
        "auth_type": "oauth2_pkce",
        "cart_supported": True,
    },
    "lenta": {
        "id": "lenta",
        "name": "Лента",
        "auth_type": "address",
        "cart_supported": True,
        "hint": "Укажите адрес доставки — магазин подберётся автоматически.",
    },
    "auchan": {
        "id": "auchan",
        "name": "Ашан",
        "auth_type": "merchant",
        "cart_supported": False,
        "hint": "Укажите ссылку на магазин /shop/<id>/ или merchantId.",
    },
}


def _user_or_401(request: Request) -> dict:
    user = get_current_user(request)
    if not user or not user.get("id"):
        raise HTTPException(401, "Unauthorized")
    return user


def _parse_merchant_id(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    match = re.search(r"/shop/(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if text.isdigit():
        return int(text)
    return None


def _auchan_item(product) -> dict:
    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "price": product.price_value,
        "old_price": product.old_price_value,
        "price_per": product.price_per,
        "price_per_kg": product.price_per_kg,
        "stock": product.stock_qty,
        "store_id": product.store_id,
        "brand": product.brandName,
        "image": product.imageUrl,
        "package": product.package_display,
        "rating": product.rating,
        "url": product.url,
    }


@router.get("")
async def list_stores(request: Request):
    user = _user_or_401(request)
    owner_id = user["id"]
    stores = []
    for store_id, meta in SUPPORTED_STORES.items():
        if store_id == "lenta":
            setting = await store_settings.get(owner_id, "lenta")
            address = (setting or {}).get("address")
            stores.append({
                **meta,
                "configured": True,
                "connected": bool(address),
                "address": address,
                "store_name": (setting or {}).get("store_name"),
                "store_alias_id": (setting or {}).get("store_alias_id"),
                "expires_at": None,
                "scopes": None,
            })
            continue
        if store_id == "auchan":
            setting = await store_settings.get(owner_id, "auchan")
            merchant_id = (setting or {}).get("merchant_id")
            stores.append({
                **meta,
                "configured": True,
                "connected": bool(merchant_id),
                "merchant_id": merchant_id,
                "store_name": (setting or {}).get("store_name"),
                "expires_at": None,
                "scopes": None,
            })
            continue
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


@router.post("/{store_id}/settings")
async def save_store_settings(
    store_id: str,
    request: Request,
    payload: dict = Body(...),
):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    if store_id == "auchan":
        raw = (
            payload.get("shop_url")
            or payload.get("merchant_id")
            or payload.get("address")
            or ""
        )
        merchant_id = _parse_merchant_id(str(raw))
        if not merchant_id:
            raise HTTPException(
                400,
                "Укажите ссылку на магазин вида https://www.auchan.ru/shop/622/ "
                "или числовой merchantId",
            )
        try:
            ok = await auchan_client.merchant_has_products(merchant_id)
        except AuchanAPIError as exc:
            raise HTTPException(502, f"Ашан API: {exc}") from exc
        if not ok:
            raise HTTPException(400, "Магазин не найден или в нём нет товаров")
        saved = await store_settings.upsert(
            user["id"],
            "auchan",
            merchant_id=merchant_id,
            store_name=f"Ашан #{merchant_id}",
        )
        return {
            "ok": True,
            "store_id": store_id,
            "merchant_id": saved["merchant_id"],
            "store_name": saved["store_name"],
        }
    if store_id != "lenta":
        raise HTTPException(400, "У этого магазина настройки не поддерживаются")
    address = str(payload.get("address") or "").strip()[:300]
    if not address:
        raise HTTPException(400, "Укажите адрес доставки")
    try:
        resolved = await lenta_resolve_store(address=address, channel="lo")
    except LentaMCPError as exc:
        raise HTTPException(502, f"Лента MCP error: {exc}") from exc

    hubs = resolved.get("hubs") or []
    def _hub_score(hub: dict) -> tuple[int, int]:
        fmt = str(hub.get("format") or "").lower()
        priority = {"super": 0, "hyper": 1, "mm": 2}.get(fmt, 3)
        try:
            distance = int(hub.get("distance") or 10**9)
        except (TypeError, ValueError):
            distance = 10**9
        return priority, distance

    usable = [
        hub for hub in hubs
        if str(hub.get("format") or "").lower() in ("super", "hyper")
        and hub.get("aliasId")
    ]
    best = min(usable, key=_hub_score) if usable else None
    saved = await store_settings.upsert(
        user["id"],
        "lenta",
        address=str(resolved.get("addressUsed") or address),
        store_alias_id=int(best["aliasId"]) if best else None,
        store_name=str(best.get("name")) if best else None,
    )
    return {
        "ok": True,
        "store_id": store_id,
        "address": saved["address"],
        "store_alias_id": saved["store_alias_id"],
        "store_name": saved["store_name"],
        "hubs": hubs,
    }


@router.post("/{store_id}/search")
async def search_store(
    store_id: str,
    request: Request,
    payload: dict = Body(...),
):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    query = str(payload.get("query") or "").strip()[:200]
    if not query:
        raise HTTPException(400, "Укажите поисковый запрос")
    if store_id == "auchan":
        setting = await store_settings.get(user["id"], "auchan")
        merchant_id = (setting or {}).get("merchant_id")
        if not merchant_id:
            raise HTTPException(400, "Сначала укажите магазин Ашана")
        try:
            products, total = await auchan_client.search(query, merchant_id)
        except AuchanAPIError as exc:
            raise HTTPException(502, f"Ашан API: {exc}") from exc
        return {
            "store_id": store_id,
            "store_name": (setting or {}).get("store_name"),
            "merchant_id": merchant_id,
            "total": total,
            "items": [_auchan_item(p) for p in products],
        }
    if store_id != "lenta":
        raise HTTPException(400, "Поиск поддерживается только для Ленты и Ашана")
    setting = await store_settings.get(user["id"], "lenta")
    address = (setting or {}).get("address")
    if not address:
        raise HTTPException(400, "Сначала укажите адрес доставки Ленты")
    try:
        resolved_store, products = await lenta_products_search(
            query,
            address=address,
            store_id=(setting or {}).get("store_alias_id"),
        )
    except LentaMCPError as exc:
        raise HTTPException(502, f"Лента MCP error: {exc}") from exc
    return {
        "store_id": store_id,
        "store_name": (setting or {}).get("store_name"),
        "lenta_store_id": resolved_store,
        "items": [p.model_dump() for p in products],
    }


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
    elif store_id in ("lenta", "auchan"):
        await store_settings.delete(user["id"], store_id)
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
    if store_id == "lenta":
        setting = await store_settings.get(user["id"], "lenta")
        address = (setting or {}).get("address")
        if not address:
            raise HTTPException(400, "Сначала укажите адрес доставки Ленты")
        try:
            resolved_store, products = await lenta_products_search(
                "молоко",
                address=address,
                store_id=(setting or {}).get("store_alias_id"),
            )
        except LentaMCPError as exc:
            raise HTTPException(502, f"Лента MCP error: {exc}") from exc
        return {
            "ok": True,
            "store_id": store_id,
            "address": address,
            "lenta_store_id": resolved_store,
            "store_name": (setting or {}).get("store_name"),
            "mcp_products": len(products),
            "sample": products[0].name if products else None,
            "message": "MCP Ленты работает.",
        }
    if store_id == "auchan":
        setting = await store_settings.get(user["id"], "auchan")
        merchant_id = (setting or {}).get("merchant_id")
        if not merchant_id:
            raise HTTPException(400, "Сначала укажите магазин Ашана")
        try:
            products, total = await auchan_client.search("молоко", merchant_id)
        except AuchanAPIError as exc:
            raise HTTPException(502, f"Ашан API: {exc}") from exc
        return {
            "ok": True,
            "store_id": store_id,
            "merchant_id": merchant_id,
            "store_name": (setting or {}).get("store_name"),
            "products": len(products),
            "total": total,
            "sample": products[0].name if products else None,
            "message": "Поиск Ашана работает.",
        }
    return {"ok": True, "store_id": store_id}


@router.post("/{store_id}/cart")
async def build_store_cart(store_id: str, request: Request):
    user = _user_or_401(request)
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(404, "Unknown store")
    if store_id == "auchan":
        try:
            result = await auchan_links.build_links(
                owner_id=user["id"],
                user_id=user["id"],
                store_id="auchan",
                user=user,
            )
        except auchan_links.StoreNotConfigured as exc:
            raise HTTPException(400, str(exc)) from exc
        except AuchanAPIError as exc:
            raise HTTPException(502, f"Ашан API: {exc}") from exc
        return result
    if store_id == "lenta":
        try:
            result = await lenta_cart.build_cart(
                owner_id=user["id"],
                user_id=user["id"],
                store_id="lenta",
                user=user,
            )
        except lenta_cart.StoreNotConfigured as exc:
            raise HTTPException(400, str(exc)) from exc
        except LentaMCPError as exc:
            raise HTTPException(502, f"Лента MCP error: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
        return result
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
    result.setdefault("store_name", "ВкусВилл")
    return result
