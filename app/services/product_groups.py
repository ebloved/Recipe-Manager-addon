"""Логические продукты и GTIN-варианты.

`identity_key` описывает один и тот же продукт без привязки к GTIN:
бренд, тип, объём, упаковка, вариант. GTIN/штрихкод — это вариант.
"""
from __future__ import annotations

import re
from typing import Any

_VOLUME_RE = re.compile(
    r"(\d+(?:[.,/]\d+)?)\s*(мл|ml|л|l|кг|kg|г|гр|g)\b",
    re.IGNORECASE,
)
_PACKAGING = (
    ("жест", "can"),
    ("банк", "can"),
    ("бутыл", "bottle"),
    ("стекл", "glass"),
    ("пластик", "plastic"),
    ("пакет", "bag"),
    ("короб", "box"),
    ("тетра", "tetra"),
)
_VARIANTS = (
    ("zero", "zero"),
    ("зеро", "zero"),
    ("cherry", "cherry"),
    ("вишн", "cherry"),
    ("light", "light"),
    ("лайт", "light"),
    ("классич", "classic"),
)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def _volume(value: Any, name: str) -> str:
    raw = str(value or "").strip()
    text = raw or name
    match = _VOLUME_RE.search(text)
    if not match:
        return _norm(raw)
    try:
        amount = float(match.group(1).replace(",", ".").replace("/", "."))
    except ValueError:
        return _norm(raw)
    unit = match.group(2).lower()
    if unit in ("л", "l"):
        amount *= 1000
        unit = "ml"
    elif unit in ("кг", "kg"):
        amount *= 1000
        unit = "g"
    elif unit in ("гр", "g", "г"):
        unit = "g"
    elif unit == "мл":
        unit = "ml"
    if amount.is_integer():
        amount = int(amount)
    return f"{amount}{unit}"


def _packaging(value: Any, name: str) -> str:
    raw = _norm(value)
    text = raw or _norm(name)
    for marker, code in _PACKAGING:
        if marker in text:
            return code
    return raw


def _variant(value: Any, name: str) -> str:
    raw = _norm(value)
    text = raw or _norm(name)
    for marker, code in _VARIANTS:
        if marker in text:
            return code
    return raw


def identity_key(fields: dict[str, Any], *, name: str | None = None) -> str:
    explicit = fields.get("identity_key") or fields.get("group_key")
    if explicit:
        return _norm(explicit)
    product_name = str(name or fields.get("name") or "")
    brand = _norm(fields.get("brand"))
    product_type = _norm(fields.get("product_type") or fields.get("category"))
    volume = _volume(fields.get("volume"), product_name)
    packaging = _packaging(fields.get("packaging"), product_name)
    variant = _variant(fields.get("variant"), product_name)
    # Структурный ключ строим только когда есть объём и хоть что-то
    # уточняющее (бренд/тип). Иначе легко склеить всю категорию «Напитки».
    if volume and (brand or _norm(fields.get("product_type"))):
        return "|".join([brand, product_type, volume, packaging, variant])
    # Консервативный fallback: без GTIN, но с именем и категорией.
    return "|".join([
        _norm(product_name),
        _norm(fields.get("category")),
        brand,
    ])


def group_fields(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_key": identity_key(product, name=product.get("name")),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "product_type": product.get("product_type") or product.get("category"),
        "volume": _volume(product.get("volume"), product.get("name") or ""),
        "packaging": _packaging(product.get("packaging"), product.get("name") or ""),
        "variant": _variant(product.get("variant"), product.get("name") or ""),
    }
