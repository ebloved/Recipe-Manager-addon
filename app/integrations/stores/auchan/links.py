"""Подбор товаров Ашана под список покупок и ссылки на карточки.

Публичной корзины у Ашана нет, поэтому результат — список товаров
со ссылками, ценами и ориентировочным количеством.
"""
from __future__ import annotations

import asyncio
import math
import re
from typing import Any

from config import AUCHAN_MAX_LINKS
from integrations.stores.auchan import client as auchan
from integrations.stores.auchan.matcher import pick_batch
from integrations.stores.auchan.models import AuchanProduct, MatchItem
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


def _is_piece_item(item: dict[str, Any]) -> bool:
    return (
        item.get("sold_as") == "piece"
        and (item.get("suggested_unit") or "").strip().lower() in _PIECE_UNITS
    )


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


def _queries(item: dict[str, Any]) -> list[str]:
    query = _search_query(item)
    if not query:
        return []
    words = [w for w in re.split(r"\s+", query) if len(w) > 2]
    out = [query]
    if len(words) > 1 and words[0].lower() != query.lower():
        out.append(words[0])
    return out


def _quantity_label(
    item: dict[str, Any], product: AuchanProduct
) -> tuple[float, str, str | None]:
    quantity = _to_float(item.get("suggested_quantity"))
    if quantity is None or quantity <= 0:
        return 1.0, "1 уп.", "нет количества"
    unit = (item.get("suggested_unit") or "").strip().lower()

    if product.is_weighted:
        grams = _to_grams(quantity, unit)
        if grams is None:
            return 1.0, "по весу", "неизвестна единица веса"
        step = float(product.basketStep or 0.25) or 0.25
        kg = grams / 1000.0
        quanta = max(step, math.ceil(kg / step) * step)
        return round(quanta, 3), f"~{quanta:.2f} кг", None

    if unit in _PIECE_UNITS:
        q = max(1, math.ceil(quantity))
        return float(q), f"{q} шт", None

    grams = _to_grams(quantity, unit)
    weight = product.weight_g
    if grams is not None and weight:
        q = max(1, math.ceil(grams / weight))
        return float(q), f"{q} уп.", None
    return max(1, math.ceil(quantity)), f"{max(1, math.ceil(quantity))} уп.", (
        "неизвестен вес упаковки"
    )


async def build_links(
    *,
    owner_id: str,
    user_id: str,
    store_id: str = "auchan",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    setting = await store_settings.get(owner_id, "auchan")
    merchant_id = (setting or {}).get("merchant_id")
    if not merchant_id:
        raise StoreNotConfigured("Укажите магазин Ашана: ссылку /shop/<id>/ или merchantId")

    cart = build_connector_cart(owner_id, "auchan", user or {"id": owner_id})
    items = cart.get("items") or []
    warnings: list[str] = list(cart.get("warnings") or [])
    if not items:
        return {
            "status": "links",
            "links_only": True,
            "cart_url": None,
            "matched_items": [],
            "warnings": warnings + ["Список покупок пуст"],
            "items_count": 0,
            "store_name": "Ашан",
        }

    # Убираем предупреждение про неизвестный вес для штучных позиций:
    # для Ашана мы всё равно можем предложить N штук.
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

    searchable: list[dict[str, Any]] = []
    candidates_by_item: dict[str, list[AuchanProduct]] = {}
    for item in items:
        name = item.get("canonical_name") or ""
        if item.get("weight_unknown") and not _is_piece_item(item):
            warnings.append(f"[{name}] неизвестен вес 1 шт — пропущено")
            continue
        if _to_float(item.get("suggested_quantity")) is None:
            warnings.append(f"[{name}] нет количества — пропущено")
            continue
        if not _search_query(item):
            warnings.append(f"[{name}] пустое название — пропущено")
            continue
        searchable.append(item)
        candidates_by_item[str(item.get("id"))] = []

    async def _search(item: dict[str, Any]) -> list[AuchanProduct]:
        found: list[AuchanProduct] = []
        seen: set[int] = set()
        try:
            for query in _queries(item):
                products, _ = await auchan.auchan_client.search(query, merchant_id)
                for product in products:
                    if product.id in seen:
                        continue
                    seen.add(product.id)
                    found.append(product)
                if len(found) >= 8:
                    break
            return [p for p in found if (p.stock_qty or 0) > 0]
        except auchan.AuchanAPIError as exc:
            warnings.append(
                f"[{item.get('canonical_name') or ''}] поиск не удался: {exc}"
            )
            return []

    results = await asyncio.gather(*[_search(item) for item in searchable])
    for item, found in zip(searchable, results):
        candidates_by_item[str(item.get("id"))] = found
        if not found:
            warnings.append(f"[{item.get('canonical_name') or ''}] не найдено в Ашане")

    match_items = [
        _match_item(item) for item in searchable
        if candidates_by_item.get(str(item.get("id")))
    ]
    picks = {}
    if match_items:
        picks = await pick_batch(
            user_id=user_id,
            items=match_items,
            candidates_by_item=candidates_by_item,
        )

    selected: list[dict[str, Any]] = []
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
            product = max(candidates, key=lambda p: (p.rating or 0, p.stock_qty or 0))
            warnings.append(
                f"[{item.get('canonical_name') or ''}] LLM не выбрал товар — "
                "взял ближайший по рейтингу"
            )
        quantity, label, warn = _quantity_label(item, product)
        if warn:
            warnings.append(f"[{item.get('canonical_name') or ''}] {warn}")
        stock = product.stock_qty
        if stock is not None and stock > 0 and quantity > stock:
            warnings.append(
                f"[{product.name}] нужно {quantity:g}, в наличии {stock:g}"
            )
            quantity = stock
            label = f"~{stock:g}" + (" кг" if product.is_weighted else " шт")
        selected.append({
            "sku": product.id,
            "product_name": product.name,
            "price": product.price_value,
            "price_per": product.price_per,
            "quantity": quantity,
            "quantity_label": label,
            "stock": stock,
            "url": product.url,
            "package": product.package_display,
            "item_names": [item.get("canonical_name")],
        })

    # Склеиваем одинаковые SKU.
    merged: dict[int, dict[str, Any]] = {}
    for row in selected:
        existing = merged.get(row["sku"])
        if existing is None:
            merged[row["sku"]] = dict(row)
            continue
        existing["quantity"] += row["quantity"]
        existing["quantity_label"] = (
            f"~{existing['quantity']:.2f} кг"
            if str(row.get("price_per", "")).startswith("weight_")
            else f"{existing['quantity']:.0f} шт"
        )
        existing["item_names"].extend(row["item_names"])

    matched = list(merged.values())
    if len(matched) > AUCHAN_MAX_LINKS:
        warnings.append(f"Список обрезан до {AUCHAN_MAX_LINKS} позиций")
        matched = matched[:AUCHAN_MAX_LINKS]

    print(
        f"[auchan] links built: {len(matched)} products, "
        f"{len(warnings)} warnings"
    )
    return {
        "status": "links",
        "links_only": True,
        "cart_url": None,
        "matched_items": matched,
        "warnings": warnings,
        "items_count": len(matched),
        "store_name": "Ашан",
    }
