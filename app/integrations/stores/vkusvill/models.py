"""Pydantic-модели ВкусВилл MCP и LLM-матчинга."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VVPrice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    current: float
    currency: str = "RUB"
    old: float | None = None
    discount_percent: float | None = None


class VVRating(BaseModel):
    model_config = ConfigDict(extra="ignore")
    average: float | None = None
    count: int | None = None


class VVWeight(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: float
    unit: str

    def to_grams(self) -> float | None:
        value = self.value
        unit = self.unit.strip().lower()
        if unit in ("кг", "kg"):
            return value * 1000.0
        if unit in ("г", "g", "гр"):
            return value
        if unit in ("л", "l"):
            return value * 1000.0
        if unit in ("мл", "ml"):
            return value
        return None


class VVProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    name: str
    price: VVPrice | None = None
    unit: str | None = None
    weight: VVWeight | float | None = None
    rating: VVRating | None = None
    url: str | None = None
    brand: str | None = None


class MatchItem(BaseModel):
    """Позиция, которую надо сматчить с товаром магазина."""

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
    packages: float = Field(default=1.0, ge=0.01, le=40.0)
    reason: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ItemPickResult(BaseModel):
    # Максимально терпимо к ответам LLM: лишнее отфильтруем/обрежем
    # в matcher._map_batch, чтобы одна плохая позиция не ломала весь батч.
    task_index: int = Field(default=0, ge=0, le=100)
    product_id: int = Field(default=0, ge=0)
    packages: float = Field(default=1.0, ge=0.0, le=40.0)
    reason: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0)


class BatchPick(BaseModel):
    items: list[ItemPickResult] = Field(default_factory=list)
