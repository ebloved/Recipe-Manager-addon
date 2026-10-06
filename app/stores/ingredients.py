"""Хранилище справочника продуктов.

- Инициализация из base_products.json при первом запуске.
- Детерминированные UUID для базовых продуктов и продуктов OFF.
- CRUD, мягкое удаление, алиасы, векторы.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import BASE_PRODUCTS_FILE, INGREDIENTS_FILE


# --- Детерминированные UUID ------------------------------------------------

_BASE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "recipe-manager:base")
_OFF_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "recipe-manager:off")


def base_product_id(key: str) -> str:
    """UUID базового продукта. Стабилен между версиями плагина."""
    return str(uuid.uuid5(_BASE_NAMESPACE, key))


def off_product_id(barcode: str) -> str:
    """UUID продукта, пришедшего из OpenFoodFacts (по штрих-коду)."""
    return str(uuid.uuid5(_OFF_NAMESPACE, str(barcode).strip()))


def new_product_id() -> str:
    """UUID для продукта, созданного пользователем."""
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Нормализация имён -----------------------------------------------------

_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Базовая нормализация для поиска по имени/алиасу.

    lowercase + схлопывание пробелов + обрезка.
    Стемминг и остальное — задача matcher-каскада, здесь только минимум.
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = _WS_RE.sub(" ", s)
    return s


# --- EAN-13 --------------------------------------------------------------

def is_internal_barcode(barcode: str) -> bool:
    """Внутренний код магазина (весовой товар). Префикс 20–29 по GS1."""
    b = (barcode or "").strip()
    if len(b) < 2 or not b.isdigit():
        return False
    return b[:2] in {f"2{i}" for i in range(10)}


# --- Хранилище ------------------------------------------------------------

class IngredientsStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path = INGREDIENTS_FILE) -> None:
        self.path = path
        self.products: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # --- Загрузка / сохранение ----------------------------------------

    async def load(self) -> None:
        if self.path.exists():
            await self._load_from_file()
        else:
            await self._init_from_base()
        added = await self._merge_from_base()
        print(
            f"[ingredients] loaded {len(self.products)} products"
            + (f" (+{added} from base)" if added else "")
        )

    async def _load_from_file(self) -> None:
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            items = data.get("products", [])
            self.products = {p["id"]: p for p in items if p.get("id")}
        except Exception as exc:  # noqa: BLE001
            print(f"[ingredients] failed to load: {exc}")
            self.products = {}

    async def _init_from_base(self) -> None:
        """Первичная инициализация из base_products.json."""
        if not BASE_PRODUCTS_FILE.exists():
            print(f"[ingredients] base file not found: {BASE_PRODUCTS_FILE}")
            self.products = {}
            return
        try:
            async with aiofiles.open(BASE_PRODUCTS_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[ingredients] failed to init from base: {exc}")
            self.products = {}
            return

        now = _now()
        for item in data.get("products", []):
            key = item.get("key")
            if not key:
                continue
            product = self._base_item_to_product(item, now)
            self.products[product["id"]] = product
        await self._save_to_file()

    async def _merge_from_base(self) -> int:
        """Добавляет новые продукты из base, которых нет локально по key.

        Существующие не трогает — это позволяет пользователю редактировать
        базовые продукты, не теряя свои правки при обновлении плагина.
        Удалённые (soft delete) не воскрешает.
        """
        if not BASE_PRODUCTS_FILE.exists():
            return 0
        try:
            async with aiofiles.open(BASE_PRODUCTS_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[ingredients] failed to read base for merge: {exc}")
            return 0

        existing_keys = {p.get("key") for p in self.products.values() if p.get("key")}
        now = _now()
        added = 0
        for item in data.get("products", []):
            key = item.get("key")
            if not key or key in existing_keys:
                continue
            product = self._base_item_to_product(item, now)
            self.products[product["id"]] = product
            added += 1

        if added:
            await self._save_to_file()
        return added

    def _base_item_to_product(self, item: dict[str, Any], now: str) -> dict[str, Any]:
        """Преобразует запись base_products.json в полноценный продукт."""
        key = item["key"]
        return {
            "id": base_product_id(key),
            "key": key,
            "name": item.get("name", ""),
            "category": item.get("category"),
            "kind": item.get("kind", "weighted"),
            "barcode": None,
            "brand": None,
            "aliases": list(item.get("aliases") or []),
            "nutrition_per_100g": dict(item.get("nutrition_per_100g") or {}),
            "default_unit": item.get("default_unit", "г"),
            "image_url": None,
            "source": "base",
            "off_last_sync": None,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "vectors": {},
        }

    async def _save_to_file(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "products": list(self.products.values()),
            }
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def save(self) -> None:
        await self._save_to_file()

    # --- Чтение --------------------------------------------------------

    def get_all(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        items = list(self.products.values())
        if not include_deleted:
            items = [p for p in items if not p.get("deleted")]
        return sorted(
            items,
            key=lambda p: ((p.get("category") or ""), (p.get("name") or "").lower()),
        )

    def get(self, product_id: str) -> dict[str, Any] | None:
        return self.products.get(product_id)

    def find_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        b = (barcode or "").strip()
        if not b:
            return None
        for p in self.products.values():
            if not p.get("deleted") and p.get("barcode") == b:
                return p
        return None

    def find_by_key(self, key: str) -> dict[str, Any] | None:
        for p in self.products.values():
            if not p.get("deleted") and p.get("key") == key:
                return p
        return None

    def find_by_name(self, name: str) -> dict[str, Any] | None:
        """Точное совпадение по нормализованному имени или алиасу."""
        needle = normalize_name(name)
        if not needle:
            return None
        for p in self.products.values():
            if p.get("deleted"):
                continue
            if normalize_name(p.get("name") or "") == needle:
                return p
            for alias in p.get("aliases") or []:
                if normalize_name(alias) == needle:
                    return p
        return None

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Простой подстрочный поиск по name и aliases."""
        q = normalize_name(query)
        if not q:
            return self.get_all()[:limit]
        result: list[dict[str, Any]] = []
        for p in self.products.values():
            if p.get("deleted"):
                continue
            if q in normalize_name(p.get("name") or ""):
                result.append(p)
                if len(result) >= limit:
                    break
                continue
            for alias in p.get("aliases") or []:
                if q in normalize_name(alias):
                    result.append(p)
                    break
            if len(result) >= limit:
                break
        return result

    def all_categories(self) -> list[str]:
        cats: set[str] = set()
        for p in self.products.values():
            if p.get("deleted"):
                continue
            c = p.get("category")
            if c:
                cats.add(c)
        return sorted(cats)

    # --- Изменение ----------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        product_id = data.get("id")
        if not product_id:
            barcode = (data.get("barcode") or "").strip()
            if barcode:
                product_id = off_product_id(barcode)
            else:
                product_id = new_product_id()

        product = {
            "id": product_id,
            "key": data.get("key"),
            "name": (data.get("name") or "").strip(),
            "category": data.get("category"),
            "kind": data.get("kind", "manual"),
            "barcode": (data.get("barcode") or "").strip() or None,
            "brand": data.get("brand"),
            "aliases": list(data.get("aliases") or []),
            "nutrition_per_100g": dict(data.get("nutrition_per_100g") or {}),
            "default_unit": data.get("default_unit") or "г",
            "image_url": data.get("image_url"),
            "source": data.get("source", "manual"),
            "off_last_sync": data.get("off_last_sync"),
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "vectors": dict(data.get("vectors") or {}),
        }
        self.products[product_id] = product
        await self._save_to_file()
        return product

    async def update(self, product_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        p = self.products.get(product_id)
        if not p:
            return None

        allowed = {
            "name", "category", "kind", "barcode", "brand", "aliases",
            "nutrition_per_100g", "default_unit", "image_url",
            "off_last_sync", "deleted", "vectors",
        }
        for k, v in patch.items():
            if k in allowed:
                p[k] = v
        p["updated_at"] = _now()
        await self._save_to_file()
        return p

    async def soft_delete(self, product_id: str) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        p["deleted"] = True
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    async def restore(self, product_id: str) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        p["deleted"] = False
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    async def hard_delete(self, product_id: str) -> bool:
        if product_id in self.products:
            del self.products[product_id]
            await self._save_to_file()
            return True
        return False

    # --- Алиасы -------------------------------------------------------

    async def add_alias(self, product_id: str, alias: str) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        a = (alias or "").strip()
        if not a:
            return False
        aliases = list(p.get("aliases") or [])
        if a in aliases:
            return False
        aliases.append(a)
        p["aliases"] = aliases
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    async def remove_alias(self, product_id: str, alias: str) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        aliases = list(p.get("aliases") or [])
        if alias not in aliases:
            return False
        aliases.remove(alias)
        p["aliases"] = aliases
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    # --- Векторы ------------------------------------------------------

    def get_vector(self, product_id: str, model_key: str) -> list[float] | None:
        p = self.products.get(product_id)
        if not p:
            return None
        return (p.get("vectors") or {}).get(model_key)

    async def set_vector(
        self, product_id: str, model_key: str, vector: list[float]
    ) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        vectors = dict(p.get("vectors") or {})
        vectors[model_key] = vector
        p["vectors"] = vectors
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    def all_vectors(self, model_key: str) -> list[tuple[str, list[float]]]:
        """[(product_id, vector), ...] для активной embedding-модели."""
        result: list[tuple[str, list[float]]] = []
        for pid, p in self.products.items():
            if p.get("deleted"):
                continue
            v = (p.get("vectors") or {}).get(model_key)
            if v:
                result.append((pid, v))
        return result


ingredients_store = IngredientsStore()