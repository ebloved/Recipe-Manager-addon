"""Сборка корзины ВкусВилла: fast path по SKU + slow path через LLM."""
from __future__ import annotations

import asyncio
import math
from typing import Any

from config import VKUSVILL_MAX_CART_ITEMS
from integrations.stores.vkusvill import client as vv
from integrations.stores.vkusvill.matcher import pick_batch
from integrations.stores.vkusvill.mcp_client import MCPError, MCPUnauthorized
from integrations.stores.vkusvill.models import MatchItem, ProductPick, VVProduct
from integrations.stores.vkusvill.oauth import get_valid_access_token
from services.connector_export import build_connector_cart
from stores.product_offers import make_item_key, product_offers

_UNIT_TO_GRAMS = {
    "г": 1.0, "гр": 1.0, "g": 1.0,
    "кг": 1000.0, "kg": 1000.0,
    "мл": 1.0, "ml": 1.0,
    "л": 1000.0, "l": 1000.0,
}
_PIECE_UNITS = {
    "шт", "штук", "штука", "штуки", "банка", "банки",
    "зубчик", "зубчика", "пучок", "пучка", "упаковка", "уп", "пачка", "пакет",
    "щепотка", "щепоть", "веточка",
}


_WEIGHT_ITEM_UNITS = {"г", "гр", "g", "кг", "kg", "мл", "ml", "л", "l"}
_CACHE_VERSION = 2


def _cache_is_stale(item: dict[str, Any], cached: dict[str, Any]) -> bool:
    """Старый кеш упакованного товара для весового ингредиента.

    Раньше подбор не учитывал unit/цену за кг и мог закешировать пачку.
    Такие записи (match_version < 2) перепроверяем один раз.
    """
    item_unit = (item.get("suggested_unit") or "").strip().lower()
    cached_unit = (cached.get("unit") or "").strip().lower()
    if item_unit not in _WEIGHT_ITEM_UNITS or not cached_unit:
        return False
    if cached_unit in ("кг", "kg", "л", "l"):
        return False
    try:
        version = int(cached.get("match_version") or 1)
    except (TypeError, ValueError):
        version = 1
    return version < _CACHE_VERSION


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _clamp_q(value: float) -> float:
    return round(min(max(value, 0.01), 40.0), 3)


def _weight_g(product: VVProduct | None) -> float | None:
    if product is None or product.weight is None:
        return None
    weight = product.weight
    if hasattr(weight, "to_grams"):
        return weight.to_grams()
    try:
        return float(weight)
    except (TypeError, ValueError):
        return None


def _calc_q(item: dict[str, Any], product: VVProduct | None) -> tuple[float, str | None]:
    unit = (item.get("suggested_unit") or "").strip().lower()
    quantity = _to_float(item.get("suggested_quantity"))
    if quantity is None or quantity <= 0:
        return 1.0, "no suggested_quantity; assuming 1 package"

    product_unit = (product.unit or "").strip().lower() if product else ""

    # Весовой/объёмный товар: unit="кг"/"л", weight=null.
    # В MCP q для такого товара — это килограммы/литры, а не упаковки.
    if product_unit in ("кг", "kg", "л", "l"):
        if unit in ("кг", "kg", "л", "l"):
            return _clamp_q(quantity), None
        factor = _UNIT_TO_GRAMS.get(unit)
        if factor is None:
            return 1.0, f"unknown unit {unit!r}; assuming 1 package"
        base = quantity * factor  # г или мл
        return _clamp_q(base / 1000.0), None

    # Штучный товар: q — упаковки.
    if unit in _PIECE_UNITS:
        return _clamp_q(quantity), None

    factor = _UNIT_TO_GRAMS.get(unit)
    if factor is None:
        return 1.0, f"unknown unit {unit!r}; assuming 1 package"

    weight = _weight_g(product)
    if not weight or weight <= 0:
        return 1.0, "package weight unknown; assuming 1 package"

    return _clamp_q(math.ceil((quantity * factor) / weight)), None


def _match_item(item: dict[str, Any]) -> MatchItem:
    return MatchItem(
        id=str(item.get("id")),
        name=item.get("canonical_name") or "",
        quantity=_to_float(item.get("suggested_quantity")),
        unit=item.get("suggested_unit"),
        piece_weight_g=_to_float(item.get("piece_weight_g")),
        sku_hint=item.get("sku_hint"),
        notes=item.get("notes") or "",
        weight_unknown=bool(item.get("weight_unknown")),
    )


async def _find_candidates(
    item: dict[str, Any],
    token: str,
) -> list[VVProduct]:
    hint = item.get("sku_hint") or {}
    barcode = hint.get("barcode")
    if barcode:
        exact = await vv.product_barcode(str(barcode), token=token)
        if exact:
            return [exact]
    query = hint.get("name") or item.get("canonical_name") or ""
    return await vv.products_search(query, limit=10, token=token)


async def build_cart(
    *,
    owner_id: str,
    user_id: str,
    store_id: str = "vkusvill",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cart = build_connector_cart(owner_id, store_id, user or {"id": owner_id})
    items = cart.get("items") or []
    warnings: list[str] = list(cart.get("warnings") or [])
    if not items:
        return {
            "status": "no_match",
            "cart_url": None,
            "matched_items": [],
            "warnings": warnings + ["Список покупок пуст"],
            "items_count": 0,
        }

    token = await get_valid_access_token(owner_id, store_id)
    matched: list[dict[str, Any]] = []
    cart_products: list[dict[str, Any]] = []

    fast_items: list[dict[str, Any]] = []
    slow_items: list[dict[str, Any]] = []

    for item in items:
        name = item.get("canonical_name") or ""
        if item.get("weight_unknown"):
            warnings.append(f"[{name}] неизвестен вес 1 шт — пропущено")
            continue
        if _to_float(item.get("suggested_quantity")) is None:
            warnings.append(f"[{name}] нет количества — пропущено")
            continue
        item_key = make_item_key(item.get("product_id"), name)
        item["_item_key"] = item_key
        cached = await product_offers.get(owner_id, store_id, item_key)
        if cached and cached.get("sku") and not _cache_is_stale(item, cached):
            item["_sku"] = int(cached["sku"])
            fast_items.append(item)
        else:
            slow_items.append(item)

    # --- Fast path -------------------------------------------------------
    if fast_items:
        async def _fast(item: dict[str, Any]) -> tuple[dict[str, Any], VVProduct | None]:
            product = await vv.product_details(int(item["_sku"]), token=token)
            return item, product

        results = await asyncio.gather(
            *[_fast(item) for item in fast_items],
            return_exceptions=True,
        )
        for item, result in zip(fast_items, results):
            name = item.get("canonical_name") or ""
            if isinstance(result, BaseException):
                warnings.append(f"[{name}] fast-path error: {type(result).__name__}")
                slow_items.append(item)
                continue
            _, product = result
            if product is None:
                await product_offers.delete(owner_id, store_id, item["_item_key"])
                slow_items.append(item)
                continue
            q, warning = _calc_q(item, product)
            if warning:
                warnings.append(f"[{name}] {warning}")
            cart_products.append({"id": int(item["_sku"]), "q": q})
            matched.append({
                "item_id": item.get("id"),
                "sku": int(item["_sku"]),
                "status": "linked_by_sku",
                "price": product.price.current if product.price else None,
                "product_name": product.name,
            })

    # --- Slow path -------------------------------------------------------
    if slow_items:
        async def _search(item: dict[str, Any]) -> tuple[dict[str, Any], list[VVProduct]]:
            try:
                candidates = await _find_candidates(item, token)
                return item, candidates
            except MCPError as exc:
                return item, []
            except Exception:  # noqa: BLE001
                return item, []

        search_results = await asyncio.gather(*[_search(item) for item in slow_items])
        candidates_by_item: dict[str, list[VVProduct]] = {}
        match_items: list[MatchItem] = []
        for item, candidates in search_results:
            name = item.get("canonical_name") or ""
            if not candidates:
                warnings.append(f"[{name}] не найдено во ВкусВилле")
                continue
            match_item = _match_item(item)
            candidates_by_item[match_item.id] = candidates
            match_items.append(match_item)

        if match_items:
            picks: dict[str, ProductPick] = await pick_batch(
                user_id=user_id,
                items=match_items,
                candidates_by_item=candidates_by_item,
            )
            by_id = {item.id: item for item in match_items}
            for item in slow_items:
                match_item = by_id.get(str(item.get("id")))
                if match_item is None:
                    continue
                pick = picks.get(match_item.id)
                name = item.get("canonical_name") or ""
                if pick is None or pick.product_id == 0:
                    reason = pick.reason if pick else "no_candidates"
                    warnings.append(f"[{name}] no match ({reason})")
                    continue
                candidates = candidates_by_item.get(match_item.id, [])
                product = next((p for p in candidates if p.id == pick.product_id), None)
                if product is None:
                    warnings.append(f"[{name}] LLM selected unknown product_id")
                    continue
                q, warning = _calc_q(item, product)
                if warning:
                    # Для slow path доверяем packages от LLM, если вес неизвестен.
                    q = _clamp_q(pick.packages)
                cart_products.append({"id": product.id, "q": q})
                matched.append({
                    "item_id": item.get("id"),
                    "sku": product.id,
                    "status": "matched_by_llm",
                    "price": product.price.current if product.price else None,
                    "product_name": product.name,
                })
                await product_offers.upsert(
                    owner_id,
                    store_id,
                    item["_item_key"],
                    sku=product.id,
                    product_name=product.name,
                    price=product.price.current if product.price else None,
                    weight_g=_weight_g(product),
                    unit=product.unit,
                )

    # --- Merge + cap -----------------------------------------------------
    merged: dict[int, float] = {}
    for product in cart_products:
        sku = int(product["id"])
        total = merged.get(sku, 0.0) + float(product["q"])
        if total > 40:
            warnings.append(f"sku={sku}: q > 40, обрезано до 40")
            total = 40.0
        merged[sku] = total

    final_products = [
        {"id": sku, "q": round(q, 3)}
        for sku, q in merged.items()
    ]
    if len(final_products) > VKUSVILL_MAX_CART_ITEMS:
        warnings.append(
            f"Корзина обрезана до {VKUSVILL_MAX_CART_ITEMS} позиций"
        )
        final_products = final_products[:VKUSVILL_MAX_CART_ITEMS]
        final_skus = {p["id"] for p in final_products}
        matched = [m for m in matched if m.get("sku") in final_skus]

    if not final_products:
        return {
            "status": "no_match",
            "cart_url": None,
            "matched_items": matched,
            "warnings": warnings,
            "items_count": 0,
        }

    try:
        cart_url = await vv.cart_link_create(final_products, token=token)
    except MCPUnauthorized:
        raise
    except MCPError as exc:
        raise RuntimeError(f"cart_link_create failed: {exc}") from exc

    print(
        f"[vkusvill] cart built: {len(final_products)} products, "
        f"{len(matched)} matched, {len(warnings)} warnings"
    )
    return {
        "status": "ok",
        "cart_url": cart_url,
        "matched_items": matched,
        "warnings": warnings,
        "items_count": len(final_products),
    }
