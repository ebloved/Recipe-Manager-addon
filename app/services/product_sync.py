"""Приём наблюдений товаров из внешних источников.

Ничего не добавляет в общий справочник автоматически: совпадения
привязываются по barcode/имени, новые товары создают suggestion для админа.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from db import SessionLocal
from stores import ingredients_store
from stores.db_models import ProductObservation, ProductSuggestion

_BARCODE_RE = re.compile(r"\D+")


def normalize_barcode(value: Any) -> str | None:
    raw = _BARCODE_RE.sub("", str(value or ""))
    if not raw:
        return None
    if len(raw) == 14 and raw.startswith("0"):
        raw = raw[1:]
    if not (8 <= len(raw) <= 14):
        return None
    return raw


def _clean(value: Any, limit: int = 500) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


async def _find_pending_suggestion(
    session,
    *,
    barcode: str | None,
    name: str,
    brand: str | None,
) -> ProductSuggestion | None:
    query = select(ProductSuggestion).where(ProductSuggestion.status == "pending")
    if barcode:
        result = await session.execute(query.where(ProductSuggestion.barcode == barcode))
        row = result.scalars().first()
        if row:
            return row
    result = await session.execute(
        query.where(
            ProductSuggestion.barcode.is_(None),
            ProductSuggestion.name == name,
            ProductSuggestion.brand == brand,
        )
    )
    return result.scalars().first()


async def record_observations(
    owner_id: str,
    items: list[dict[str, Any]],
    *,
    shopping_mode: str = "check",
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    enriched: list[dict[str, Any]] = []
    feedback_items: list[dict[str, Any]] = []
    warnings: list[str] = []
    observed = 0

    async with SessionLocal() as session:
        for raw in items:
            if not isinstance(raw, dict):
                continue
            name = _clean(raw.get("name"), 500)
            if not name:
                warnings.append("Пропущена позиция без name")
                continue
            barcode = normalize_barcode(raw.get("barcode") or raw.get("gtin"))
            brand = _clean(raw.get("brand"), 200)
            category = _clean(raw.get("category"), 200)
            unit = _clean(raw.get("unit"), 32)
            external_id = _clean(raw.get("external_id"), 200)
            amount = raw.get("amount")
            if amount is not None:
                amount = str(amount)[:64]
            price = raw.get("price")
            try:
                price = float(price) if price not in (None, "") else None
            except (TypeError, ValueError):
                price = None
            purchased_at = _clean(raw.get("purchased_at"), 64)
            store = _clean(raw.get("store"), 200)

            product = None
            matched_by = None
            if barcode:
                product = ingredients_store.find_by_barcode(barcode)
                if product:
                    matched_by = "barcode"
            if product is None:
                product = ingredients_store.find_by_name(name)
                if product:
                    matched_by = "name"

            product_id = product.get("id") if product else None
            suggestion_id = None
            if product and product_id:
                patch: dict[str, Any] = {}
                if barcode and product.get("barcode") and str(product["barcode"]) != barcode:
                    warnings.append(
                        f"[{name}] у продукта уже другой штрихкод "
                        f"{product.get('barcode')} — не перезаписываю"
                    )
                if barcode and not product.get("barcode"):
                    patch["barcode"] = barcode
                if brand and not product.get("brand"):
                    patch["brand"] = brand
                if category and not product.get("category"):
                    patch["category"] = category
                if unit and not product.get("default_unit"):
                    patch["default_unit"] = unit
                if patch:
                    updated = await ingredients_store.update(product_id, patch)
                    if updated:
                        enriched.append({
                            "product_id": product_id,
                            "fields": sorted(patch.keys()),
                        })
            if not product_id:
                suggestion = await _find_pending_suggestion(
                    session, barcode=barcode, name=name, brand=brand
                )
                payload = {
                    "name": name,
                    "barcode": barcode,
                    "brand": brand,
                    "category": category,
                    "unit": unit,
                    "source": "external",
                }
                if suggestion is None:
                    suggestion = ProductSuggestion(
                        id=uuid.uuid4().hex,
                        owner_id=str(owner_id),
                        barcode=barcode,
                        name=name,
                        brand=brand,
                        category=category,
                        unit=unit,
                        payload_json=json.dumps(payload, ensure_ascii=False)[:8000],
                        status="pending",
                    )
                    session.add(suggestion)
                    await session.flush()
                else:
                    # Обновляем недостающие поля, не меняя статус.
                    suggestion.name = suggestion.name or name
                    suggestion.brand = suggestion.brand or brand
                    suggestion.category = suggestion.category or category
                    suggestion.unit = suggestion.unit or unit
                suggestion_id = suggestion.id
                suggestions.append({
                    "external_id": external_id,
                    "suggestion_id": suggestion_id,
                    "status": "pending",
                })

            if raw.get("shopping_item_id") or raw.get("purchased") is not None:
                feedback_items.append(raw)

            observation = ProductObservation(
                id=uuid.uuid4().hex,
                owner_id=str(owner_id),
                external_id=external_id,
                name=name,
                barcode=barcode,
                brand=brand,
                category=category,
                unit=unit,
                amount=amount,
                price=price,
                store=store,
                purchased_at=purchased_at,
                product_id=product_id,
                matched_by=matched_by,
                raw_json=json.dumps(raw, ensure_ascii=False)[:8000],
            )
            session.add(observation)
            observed += 1
            if product_id:
                matched.append({
                    "external_id": external_id,
                    "product_id": product_id,
                    "matched_by": matched_by,
                })
        await session.commit()

    shopping = None
    if feedback_items:
        from services.shopping_feedback import apply_purchase_feedback
        shopping = await apply_purchase_feedback(
            owner_id, feedback_items, mode=shopping_mode
        )

    return {
        "observed": observed,
        "matched": matched,
        "suggestions": suggestions,
        "enriched": enriched,
        "shopping": shopping,
        "warnings": warnings,
    }


async def list_suggestions(status: str | None = "pending") -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        query = select(ProductSuggestion).order_by(ProductSuggestion.created_at.desc())
        if status:
            query = query.where(ProductSuggestion.status == status)
        rows = (await session.execute(query)).scalars().all()
    return [
        {
            "id": row.id,
            "owner_id": row.owner_id,
            "barcode": row.barcode,
            "name": row.name,
            "brand": row.brand,
            "category": row.category,
            "unit": row.unit,
            "status": row.status,
            "product_id": row.product_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def approve_suggestion(
    suggestion_id: str,
    *,
    admin_id: str,
) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        row = await session.get(ProductSuggestion, suggestion_id)
        if row is None or row.status != "pending":
            return None
        product = None
        if row.barcode:
            product = ingredients_store.find_by_barcode(row.barcode)
        if product is None:
            payload = {}
            try:
                payload = json.loads(row.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            product = await ingredients_store.add({
                "name": row.name,
                "barcode": row.barcode,
                "brand": row.brand,
                "category": row.category,
                "default_unit": row.unit or "г",
                "source": "external",
                "kind": "manual",
                "aliases": payload.get("aliases") or [],
            })
        row.status = "approved"
        row.product_id = product.get("id")
        row.reviewed_at = datetime.now(timezone.utc)
        row.reviewed_by = str(admin_id)
        # Привязываем наблюдения с тем же barcode к продукту.
        if row.barcode:
            observations = (
                await session.execute(
                    select(ProductObservation).where(
                        ProductObservation.barcode == row.barcode
                    )
                )
            ).scalars().all()
            for obs in observations:
                obs.product_id = product.get("id")
                obs.matched_by = "suggestion"
        await session.commit()
        return product


async def reject_suggestion(
    suggestion_id: str,
    *,
    admin_id: str,
) -> bool:
    async with SessionLocal() as session:
        row = await session.get(ProductSuggestion, suggestion_id)
        if row is None or row.status != "pending":
            return False
        row.status = "rejected"
        row.reviewed_at = datetime.now(timezone.utc)
        row.reviewed_by = str(admin_id)
        await session.commit()
        return True
