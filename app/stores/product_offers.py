"""Кеш SKU магазинов (product_offers) + ключи позиций."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from db import SessionLocal
from services.shopping_normalizer import normalize_for_connector
from stores.db_models import ProductOffer


def make_item_key(product_id: Any, name: str) -> str:
    """Стабильный ключ позиции для кеша SKU."""
    if product_id not in (None, ""):
        return f"product:{product_id}"
    return f"name:{normalize_for_connector(name or '')}"


class ProductOffersRepository:
    async def get(
        self, owner_id: str, store_id: str, item_key: str
    ) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ProductOffer).where(
                    ProductOffer.owner_id == owner_id,
                    ProductOffer.store_id == store_id,
                    ProductOffer.item_key == item_key,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "sku": row.sku,
                "product_name": row.product_name,
                "price": row.price,
                "weight_g": row.weight_g,
                "unit": row.unit,
                "match_version": row.match_version,
                "updated_at": row.updated_at,
                "last_verified_at": row.last_verified_at,
            }

    async def upsert(
        self,
        owner_id: str,
        store_id: str,
        item_key: str,
        *,
        sku: int,
        product_name: str | None = None,
        price: float | None = None,
        weight_g: float | None = None,
        unit: str | None = None,
        verified: bool = True,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            result = await session.execute(
                select(ProductOffer).where(
                    ProductOffer.owner_id == owner_id,
                    ProductOffer.store_id == store_id,
                    ProductOffer.item_key == item_key,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = ProductOffer(
                    owner_id=owner_id,
                    store_id=store_id,
                    item_key=item_key,
                    sku=sku,
                )
                session.add(row)
            row.sku = int(sku)
            row.product_name = product_name
            row.price = price
            row.weight_g = weight_g
            row.unit = unit
            row.match_version = 2
            row.updated_at = now
            if verified:
                row.last_verified_at = now
            await session.commit()

    async def delete(self, owner_id: str, store_id: str, item_key: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(ProductOffer).where(
                    ProductOffer.owner_id == owner_id,
                    ProductOffer.store_id == store_id,
                    ProductOffer.item_key == item_key,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def list_for_owner(
        self, owner_id: str, store_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            stmt = select(ProductOffer).where(ProductOffer.owner_id == owner_id)
            if store_id:
                stmt = stmt.where(ProductOffer.store_id == store_id)
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [
            {
                "store_id": row.store_id,
                "item_key": row.item_key,
                "sku": row.sku,
                "product_name": row.product_name,
                "price": row.price,
                "weight_g": row.weight_g,
                "unit": row.unit,
                "match_version": row.match_version,
                "updated_at": row.updated_at,
                "last_verified_at": row.last_verified_at,
            }
            for row in rows
        ]


product_offers = ProductOffersRepository()
