"""Модели товаров Ашана."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_PACKAGE_RE = re.compile(
    r"([0-9]+(?:[.,][0-9]+)?)\s*(кг|kg|г|гр|g|л|l|мл|ml)\b",
    re.IGNORECASE,
)


def _package_grams(value: str | None) -> float | None:
    if not value:
        return None
    match = _PACKAGE_RE.search(str(value))
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = match.group(2).lower()
    if unit in ("кг", "kg", "л", "l"):
        return amount * 1000.0
    return amount


class AuchanProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    productId: int | None = None
    code: str
    name: str
    price: dict[str, Any] | None = None
    oldPrice: dict[str, Any] | None = None
    stock: dict[str, Any] | None = None
    basketStep: float | None = None
    brandName: str | None = None
    imageUrl: str | None = None
    package_display: str | None = None
    rate: dict[str, Any] | None = None
    categoryCodes: list[str] = Field(default_factory=list)
    categoryNames: list[str] = Field(default_factory=list)

    @property
    def price_value(self) -> float | None:
        value = (self.price or {}).get("value")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def price_per(self) -> str:
        return str((self.price or {}).get("per") or "item").lower()

    @property
    def old_price_value(self) -> float | None:
        value = (self.oldPrice or {}).get("value")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def stock_qty(self) -> float | None:
        value = (self.stock or {}).get("qty")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def store_id(self) -> int | None:
        value = (self.stock or {}).get("storeId")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def rating(self) -> float | None:
        value = (self.rate or {}).get("rating")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def weight_g(self) -> float | None:
        return _package_grams(self.package_display)

    @property
    def is_weighted(self) -> bool:
        return self.price_per.startswith("weight_")

    @property
    def price_per_kg(self) -> float | None:
        price = self.price_value
        if price is None:
            return None
        if self.price_per == "weight_kg":
            return price
        if self.price_per == "weight_100g":
            return price * 10.0
        weight = self.weight_g
        if weight:
            return round(price * 1000.0 / weight, 2)
        return None

    @property
    def url(self) -> str:
        return f"https://www.auchan.ru/product/{self.code}/"

    def display_price(self) -> str | None:
        price = self.price_value
        if price is None:
            return None
        unit = {
            "weight_kg": "₽/кг",
            "weight_100g": "₽/100 г",
        }.get(self.price_per, "₽")
        return f"{price:.2f} {unit}"


class MatchItem(BaseModel):
    id: str
    name: str
    quantity: float | None = None
    unit: str | None = None
    piece_weight_g: float | None = None
    sku_hint: dict[str, Any] | None = None
    notes: str | None = None
    weight_unknown: bool = False


class ProductPick(BaseModel):
    product_id: int = Field(default=0, ge=0)
    packages: float = Field(default=1.0, ge=0.01, le=100.0)
    reason: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ItemPickResult(BaseModel):
    task_index: int = Field(default=0, ge=0, le=100)
    product_id: int = Field(default=0, ge=0)
    packages: float = Field(default=1.0, ge=0.0, le=100.0)
    reason: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class BatchPick(BaseModel):
    items: list[ItemPickResult] = Field(default_factory=list)
