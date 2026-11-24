"""Обёртки над MCP-инструментами Ленты."""
from __future__ import annotations

from typing import Any

from config import LENTA_DEFAULT_CHANNEL
from integrations.stores.lenta.mcp_client import MCPError, MCPToolError, lenta_mcp
from integrations.stores.lenta.models import LentaProduct


def _location_args(
    address: str | None,
    store_id: int | None,
    channel: str | None,
) -> dict[str, Any]:
    args: dict[str, Any] = {"channel": channel or LENTA_DEFAULT_CHANNEL}
    if store_id:
        args["storeId"] = int(store_id)
    elif address:
        args["address"] = address
    else:
        raise MCPToolError("Нужен address или storeId")
    return args


async def resolve_store(
    *,
    address: str | None = None,
    store_id: int | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    return await lenta_mcp.call_tool(
        "storefront_resolve_store",
        _location_args(address, store_id, channel),
    )


async def products_search(
    query: str,
    *,
    address: str | None = None,
    store_id: int | None = None,
    channel: str | None = None,
    page: int = 1,
) -> tuple[int | None, list[LentaProduct]]:
    args = _location_args(address, store_id, channel)
    args.update({"query": query, "page": max(1, int(page))})
    data = await lenta_mcp.call_tool("storefront_products_search", args)
    resolved_store = data.get("storeId")
    items: list[LentaProduct] = []
    for raw in data.get("items") or []:
        try:
            items.append(LentaProduct.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return (int(resolved_store) if resolved_store else None), items


async def product_details(
    product_id: int,
    *,
    address: str | None = None,
    store_id: int | None = None,
    channel: str | None = None,
) -> LentaProduct | None:
    args = _location_args(address, store_id, channel)
    args["id"] = int(product_id)
    try:
        data = await lenta_mcp.call_tool("storefront_product_details", args)
    except MCPError:
        return None
    raw = data.get("item") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raw = data if isinstance(data, dict) else None
    if not raw:
        return None
    try:
        return LentaProduct.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


async def cart_link_create(items: list[dict[str, Any]]) -> str:
    data = await lenta_mcp.call_tool(
        "storefront_cart_link_create", {"items": items}
    )
    link = data.get("link") or data.get("cart_url") or data.get("url")
    if not link or not isinstance(link, str):
        raise MCPToolError(
            f"cart_link_create returned no link (keys={list(data.keys())})"
        )
    return link
