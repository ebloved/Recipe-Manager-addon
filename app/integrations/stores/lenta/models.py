"""Модели товаров Ленты и LLM-матчинга."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_PACKAGE_RE = re.compile(
    r"([0-9]+(?:[.,][0-9]+)?)\s*(кг|kg|г|гр|g|л|l|мл|ml)\b",
    re.IGNORECASE,
)


def _package_grams(value: str | None) -> float | None:
    """Парсит «43г», «1,9л», «1000 мл» в граммы (мл ≈ г)."""
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


class LentaProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    price: float | None = None
    priceRegular: float | None = None
    priceType: str | None = None
    discountPercent: float | None = None
    stock: int | None = None
    package: str | None = None
    url: str | None = None
    image: str | None = None
    brand: str | None = None
    rating: float | None = None
    ratingCount: int | None = None
    isWeight: bool = False
    weightGrams: float | None = None
    pricePerKg: float | None = None
    saleLimit: dict[str, Any] | None = None
    category: str | None = None
    nutrition: str | None = None
    ean: str | None = None

    def weight_g(self) -> float | None:
        if self.weightGrams:
            return float(self.weightGrams)
        return _package_grams(self.package)

    def sale_step(self) -> int:
        limit = self.saleLimit or {}
        try:
            return max(1, int(limit.get("step") or 1))
        except (TypeError, ValueError):
            return 1

    def sale_min(self) -> int:
        limit = self.saleLimit or {}
        try:
            return max(1, int(limit.get("min") or 1))
        except (TypeError, ValueError):
            return 1

    def sale_max(self) -> int:
        limit = self.saleLimit or {}
        try:
            return max(self.sale_min(), int(limit.get("max") or 40))
        except (TypeError, ValueError):
            return 40


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
