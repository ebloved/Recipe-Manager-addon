"""Сборка корзины Ленты из списка покупок.

Лента не требует OAuth: достаточно адреса доставки. Адрес и выбранный
хаб хранятся per-user в user_store_settings.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from config import LENTA_MAX_CART_ITEMS
from integrations.stores.lenta import client as lenta
from integrations.stores.lenta.matcher import pick_batch
from integrations.stores.lenta.mcp_client import MCPError
from integrations.stores.lenta.models import LentaProduct, MatchItem
from services.connector_export import build_connector_cart
from stores.store_settings import store_settings

_UNIT_TO_GRAMS = {
    "г": 1.0, "гр": 1.0, "g": 1.0,
    "кг": 1000.0, "kg": 1000.0,
    "мл": 1.0, "ml": 1.0,
    "л": 1000.0, "l": 1000.0,
}
_PIECE_UNITS = {
    "шт", "штук", "штука", "штуки", "банка", "банки",
    "зубчик", "зубчика", "пучок", "пучка", "упаковка", "уп",
    "пачка", "пакет", "щепотка", "щепоть", "веточка",
}


class StoreNotConfigured(Exception):
    pass


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_grams(quantity: float, unit: str | None) -> float | None:
    factor = _UNIT_TO_GRAMS.get((unit or "").strip().lower())
    return quantity * factor if factor is not None else None


def _calc_quantity(item: dict[str, Any], product: LentaProduct) -> tuple[int, str | None]:
    quantity = _to_float(item.get("suggested_quantity"))
    if quantity is None or quantity <= 0:
        return 1, "нет количества; беру 1 упаковку"
    unit = (item.get("suggested_unit") or "").strip().lower()

    if product.isWeight:
        grams = _to_grams(quantity, unit)
        weight = product.weight_g() or 1000.0
        quanta = 1 if grams is None else math.ceil(grams / weight)
        step = product.sale_step()
        quanta = math.ceil(quanta / step) * step
        return max(product.sale_min(), min(product.sale_max(), quanta)), None

    if unit in _PIECE_UNITS:
        return max(1, math.ceil(quantity)), None

    grams = _to_grams(quantity, unit)
    weight = product.weight_g()
    if grams is not None and weight:
        return max(1, math.ceil(grams / weight)), None
    return max(1, math.ceil(quantity)), "неизвестен вес упаковки; беру по количеству"


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


def _search_query(item: dict[str, Any]) -> str:
    hint = item.get("sku_hint") or {}
    return str(hint.get("name") or item.get("canonical_name") or "").strip()


def _is_piece_item(item: dict[str, Any]) -> bool:
    return (
        item.get("sold_as") == "piece"
        and (item.get("suggested_unit") or "").strip().lower() in _PIECE_UNITS
    )


async def build_cart(
    *,
    owner_id: str,
    user_id: str,
    store_id: str = "lenta",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = await store_settings.get(owner_id, "lenta")
    address = (settings or {}).get("address")
    if not address:
        raise StoreNotConfigured("Укажите адрес доставки Ленты в разделе «Магазины»")
    alias_id = (settings or {}).get("store_alias_id")

    cart = build_connector_cart(owner_id, "lenta", user or {"id": owner_id})
    items = cart.get("items") or []
    warnings: list[str] = list(cart.get("warnings") or [])
    # Для штучных товаров без веса мы всё равно можем купить N штук —
    # убираем предупреждение, которое относится к весовому подбору.
    piece_unknown = {
        (item.get("original_name") or item.get("canonical_name") or "").strip()
        for item in items
        if item.get("weight_unknown") and _is_piece_item(item)
    }
    if piece_unknown:
        warnings = [
            w for w in warnings
            if not any(w.startswith(f"{name}: неизвестен вес 1 шт") for name in piece_unknown)
        ]
    if not items:
        return {
            "status": "no_match",
            "cart_url": None,
            "matched_items": [],
            "warnings": warnings + ["Список покупок пуст"],
            "items_count": 0,
            "store_name": "Лента",
        }

    # 1. Ищем кандидатов по каждой позиции.
    searchable: list[dict[str, Any]] = []
    candidates_by_item: dict[str, list[LentaProduct]] = {}
    for item in items:
        name = item.get("canonical_name") or ""
        if item.get("weight_unknown") and not _is_piece_item(item):
            warnings.append(f"[{name}] неизвестен вес 1 шт — пропущено")
            continue
        if _to_float(item.get("suggested_quantity")) is None:
            warnings.append(f"[{name}] нет количества — пропущено")
            continue
        query = _search_query(item)
        if not query:
            warnings.append(f"[{name}] пустое название — пропущено")
            continue
        searchable.append(item)
        candidates_by_item[str(item.get("id"))] = []

    async def _search(item: dict[str, Any]) -> list[LentaProduct]:
        try:
            _, found = await lenta.products_search(
                _search_query(item),
                address=address,
                store_id=alias_id,
            )
            return [p for p in found if (p.stock or 0) > 0]
        except MCPError as exc:
            warnings.append(
                f"[{item.get('canonical_name') or ''}] поиск не удался: {exc}"
            )
            return []

    results = await asyncio.gather(*[_search(item) for item in searchable])
    for item, found in zip(searchable, results):
        candidates_by_item[str(item.get("id"))] = found
        if not found:
            warnings.append(f"[{item.get('canonical_name') or ''}] не найдено в Ленте")

    # 2. LLM выбирает товар; количество считаем детерминированно.
    match_items = [_match_item(item) for item in searchable if candidates_by_item[str(item.get("id"))]]
    picks = {}
    if match_items:
        picks = await pick_batch(
            user_id=user_id,
            items=match_items,
            candidates_by_item=candidates_by_item,
        )

    selected: list[tuple[dict[str, Any], LentaProduct, int]] = []
    for item in searchable:
        item_id = str(item.get("id"))
        candidates = candidates_by_item.get(item_id) or []
        if not candidates:
            continue
        pick = picks.get(item_id)
        product = None
        if pick and pick.product_id:
            product = next((p for p in candidates if p.id == pick.product_id), None)
        if product is None:
            product = max(candidates, key=lambda p: (p.rating or 0, p.stock or 0))
            warnings.append(
                f"[{item.get('canonical_name') or ''}] LLM не выбрал товар — "
                f"взял ближайший по рейтингу"
            )
        detail = await lenta.product_details(
            product.id, address=address, store_id=alias_id
        )
        if detail is not None:
            product = detail
        if (product.stock or 0) <= 0:
            warnings.append(
                f"[{item.get('canonical_name') or ''}] «{product.name}» нет в наличии"
            )
            continue
        quantity, warn = _calc_quantity(item, product)
        if warn:
            warnings.append(f"[{item.get('canonical_name') or ''}] {warn}")
        selected.append((item, product, quantity))

    # 3. Склеиваем одинаковые SKU и ограничиваем остатком.
    merged: dict[int, dict[str, Any]] = {}
    for item, product, quantity in selected:
        row = merged.get(product.id)
        if row is None:
            merged[product.id] = {
                "product": product,
                "quantity": quantity,
                "items": [item],
            }
        else:
            row["quantity"] += quantity
            row["items"].append(item)

    cart_products: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    for sku, row in merged.items():
        product: LentaProduct = row["product"]
        quantity = int(row["quantity"])
        stock = product.stock
        if stock is not None and stock > 0 and quantity > stock:
            warnings.append(
                f"[{product.name}] нужно {quantity}, в наличии {stock} — уменьшено"
            )
            quantity = stock
        if quantity <= 0:
            continue
        cart_products.append({"id": sku, "quantity": quantity})
        matched.append({
            "sku": sku,
            "product_name": product.name,
            "price": product.price,
            "quantity": quantity,
            "stock": product.stock,
            "url": product.url,
            "package": product.package,
            "item_names": [i.get("canonical_name") for i in row["items"]],
        })

    if len(cart_products) > LENTA_MAX_CART_ITEMS:
        warnings.append(f"Корзина обрезана до {LENTA_MAX_CART_ITEMS} позиций")
        cart_products = cart_products[:LENTA_MAX_CART_ITEMS]
        allowed = {p["id"] for p in cart_products}
        matched = [m for m in matched if m["sku"] in allowed]

    if not cart_products:
        return {
            "status": "no_match",
            "cart_url": None,
            "matched_items": matched,
            "warnings": warnings,
            "items_count": 0,
            "store_name": "Лента",
        }

    try:
        cart_url = await lenta.cart_link_create(cart_products)
    except MCPError as exc:
        raise RuntimeError(f"Не удалось создать ссылку на корзину: {exc}") from exc

    print(
        f"[lenta] cart built: {len(cart_products)} products, "
        f"{len(matched)} matched, {len(warnings)} warnings"
    )
    return {
        "status": "ok",
        "cart_url": cart_url,
        "matched_items": matched,
        "warnings": warnings,
        "items_count": len(cart_products),
        "store_name": "Лента",
    }
