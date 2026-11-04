"""Обёртки над MCP-тулами ВкусВилла."""
from __future__ import annotations

from typing import Any

from integrations.stores.vkusvill.mcp_client import (
    MCPToolError,
    vkusvill_mcp,
)
from integrations.stores.vkusvill.models import VVProduct

_SEARCH_FIELDS = ["id", "name", "price", "unit", "weight", "rating", "url"]


async def products_search(
    query: str,
    *,
    limit: int = 10,
    token: str | None = None,
    sort: str = "popularity",
) -> list[VVProduct]:
    args: dict[str, Any] = {
        "q": query,
        "limit": min(max(int(limit), 1), 10),
        "sort": sort,
        "vvonly": 0,
        "mode": "custom",
        "fields": _SEARCH_FIELDS,
    }
    data = await vkusvill_mcp.call_tool("vkusvill_products_search", args, token=token)
    raw_items = data.get("items") or []
    out: list[VVProduct] = []
    for raw in raw_items:
        try:
            out.append(VVProduct.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


async def product_barcode(barcode: str, *, token: str | None = None) -> VVProduct | None:
    if not barcode or len(barcode) != 13 or not barcode.isdigit():
        return None
    try:
        data = await vkusvill_mcp.call_tool(
            "vkusvill_product_barcode", {"barcode": barcode}, token=token
        )
    except MCPToolError:
        return None
    candidate = _extract_product(data)
    if candidate is None:
        return None
    try:
        return VVProduct.model_validate(candidate)
    except Exception:  # noqa: BLE001
        return None


async def product_details(product_id: int, *, token: str | None = None) -> VVProduct | None:
    try:
        data = await vkusvill_mcp.call_tool(
            "vkusvill_product_details", {"id": product_id}, token=token
        )
    except MCPToolError:
        return None
    candidate = _extract_product(data)
    if candidate is None:
        return None
    try:
        return VVProduct.model_validate(candidate)
    except Exception:  # noqa: BLE001
        return None


def _extract_product(data: Any) -> dict | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("id"), int):
        return data
    if isinstance(data.get("product"), dict):
        return data["product"]
    if isinstance(data.get("items"), list) and data["items"]:
        first = data["items"][0]
        return first if isinstance(first, dict) else None
    return None


async def cart_link_create(
    products: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> str:
    data = await vkusvill_mcp.call_tool(
        "vkusvill_cart_link_create", {"products": products}, token=token
    )
    url = data.get("link") or data.get("cart_url") or data.get("url")
    if not url or not isinstance(url, str):
        raise MCPToolError(
            f"cart_link_create returned no link (keys={list(data.keys())})"
        )
    return url
