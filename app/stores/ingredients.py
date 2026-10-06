"""Хранилище справочника продуктов.

- Инициализация из base_products.json при первом запуске.
- Детерминированные UUID для базовых продуктов и продуктов OFF.
- CRUD, мягкое удаление, алиасы, векторы.
- installation_id: уникальный для каждой инсталляции плагина, используется
  для merge при синхронизации через GitHub.
- Совместимость с matcher и products API: каждый продукт возвращается
  с ключом `product_id` (дублирует `id`).
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


def new_installation_id() -> str:
    """UUID инсталляции. Генерируется один раз при первом запуске."""
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Нормализация имён -----------------------------------------------------

_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Базовая нормализация для поиска по имени/алиасу."""
    if not name:
        return ""
    s = name.strip().lower()
    s = _WS_RE.sub(" ", s)
    return s


# --- EAN-13 ----------------------------------------------------------------

def is_internal_barcode(barcode: str) -> bool:
    """Внутренний код магазина (весовой товар). Префикс 20–29 по GS1."""
    b = (barcode or "").strip()
    if len(b) < 2 or not b.isdigit():
        return False
    return b[:2] in {f"2{i}" for i in range(10)}


# --- Хранилище -------------------------------------------------------------

class IngredientsStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path = INGREDIENTS_FILE) -> None:
        self.path = path
        self.products: dict[str, dict[str, Any]] = {}
        # Публичные атрибуты, которые ожидает products.py
        self.schema_version: int = self.SCHEMA_VERSION
        self.installation_id: str = ""
        self._lock = asyncio.Lock()

    # --- Совместимость: product_id как alias для id --------------------

    @staticmethod
    def _with_pid(p: dict[str, Any] | None) -> dict[str, Any] | None:
        """Добавляет ключ `product_id`, дублирующий `id`."""
        if p is None:
            return None
        if "product_id" not in p:
            pid = p.get("id")
            if pid:
                p["product_id"] = pid
        return p

    # --- Загрузка / сохранение ----------------------------------------

    async def load(self) -> None:
        if self.path.exists():
            await self._load_from_file()
        else:
            await self._init_from_base()
        added = await self._merge_from_base()

        # Гарантируем product_id у всех загруженных
        for p in self.products.values():
            self._with_pid(p)

        # Гарантируем installation_id
        if not self.installation_id:
            self.installation_id = new_installation_id()
            await self._save_to_file()

        print(
            f"[ingredients] loaded {len(self.products)} products"
            + (f" (+{added} from base)" if added else "")
            + (f", schema={self.schema_version}" if self.schema_version else "")
        )

    async def _load_from_file(self) -> None:
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())

            self.schema_version = int(data.get("schema_version") or self.SCHEMA_VERSION)
            self.installation_id = str(data.get("installation_id") or "")

            items = data.get("products", [])
            self.products = {}
            for p in items:
                # Поддерживаем оба варианта: с id и с product_id
                pid = p.get("id") or p.get("product_id")
                if not pid:
                    continue
                p["id"] = pid
                p["product_id"] = pid
                self.products[pid] = p
        except Exception as exc:  # noqa: BLE001
            print(f"[ingredients] failed to load: {exc}")
            self.products = {}

    async def _init_from_base(self) -> None:
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
        key = item["key"]
        pid = base_product_id(key)
        return {
            "id": pid,
            "product_id": pid,
            "key": key,
            "name": item.get("name", ""),
            "category": item.get("category"),
            "kind": item.get("kind", "weighted"),
            "barcode": None,
            "brand": None,
            "aliases": list(item.get("aliases") or []),
            "nutrition_per_100g": dict(item.get("nutrition_per_100g") or {}),
            "serving_size_g": None,
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
                "schema_version": self.schema_version or self.SCHEMA_VERSION,
                "installation_id": self.installation_id,
                "products": list(self.products.values()),
            }
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def save(self) -> None:
        await self._save_to_file()

    # --- Экспорт / merge (для синхронизации через GitHub) -------------

    def export(self) -> dict[str, Any]:
        """Полный экспорт ingredients.json."""
        return {
            "schema_version": self.schema_version or self.SCHEMA_VERSION,
            "installation_id": self.installation_id,
            "products": list(self.products.values()),
        }

    def merge_from(
        self,
        data: dict[str, Any],
        strategy: str = "last-write-wins",
    ) -> dict[str, int]:
        """Мержит входящий ingredients.json в текущую базу.

        strategy:
          - 'local-wins'       — при конфликте id оставляем локальный
          - 'remote-wins'      — при конфликте id заменяем на входящий
          - 'last-write-wins'  — сравниваем updated_at, свежий побеждает
                                 (по умолчанию)

        Возвращает статистику: {added, updated, skipped, removed}.
        """
        incoming = data.get("products") or []
        if not isinstance(incoming, list):
            return {"added": 0, "updated": 0, "skipped": 0, "removed": 0}

        added = updated = skipped = 0

        for p in incoming:
            if not isinstance(p, dict):
                continue
            pid = p.get("id") or p.get("product_id")
            if not pid:
                continue
            p["id"] = pid
            p["product_id"] = pid

            existing = self.products.get(pid)
            if existing is None:
                self.products[pid] = p
                added += 1
                continue

            if strategy == "local-wins":
                skipped += 1
                continue
            if strategy == "remote-wins":
                self.products[pid] = p
                updated += 1
                continue

            # last-write-wins
            local_ts = existing.get("updated_at") or ""
            remote_ts = p.get("updated_at") or ""
            if remote_ts > local_ts:
                self.products[pid] = p
                updated += 1
            else:
                skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped, "removed": 0}

    # --- Чтение (matcher- и products-совместимое) ---------------------

    def get_all(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        items = list(self.products.values())
        if not include_deleted:
            items = [p for p in items if not p.get("deleted")]
        for p in items:
            self._with_pid(p)
        return sorted(
            items,
            key=lambda p: ((p.get("category") or ""), (p.get("name") or "").lower()),
        )

    def list_all(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        """Список всех продуктов. Используется matcher'ом и products API."""
        return self.get_all(include_deleted=include_deleted)

    def get(self, product_id: str) -> dict[str, Any] | None:
        p = self.products.get(product_id)
        return self._with_pid(p)

    def get_active(self, product_id: str) -> dict[str, Any] | None:
        """Возвращает продукт, если он есть и не удалён. Иначе None."""
        p = self.products.get(product_id)
        if not p or p.get("deleted"):
            return None
        return self._with_pid(p)

    def count(self, include_deleted: bool = False) -> int:
        if include_deleted:
            return len(self.products)
        return sum(1 for p in self.products.values() if not p.get("deleted"))

    def find_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        b = (barcode or "").strip()
        if not b:
            return None
        for p in self.products.values():
            if not p.get("deleted") and p.get("barcode") == b:
                return self._with_pid(p)
        return None

    def get_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        """Alias для find_by_barcode. Используется products API."""
        return self.find_by_barcode(barcode)

    def find_by_key(self, key: str) -> dict[str, Any] | None:
        for p in self.products.values():
            if not p.get("deleted") and p.get("key") == key:
                return self._with_pid(p)
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
                return self._with_pid(p)
            for alias in p.get("aliases") or []:
                if normalize_name(alias) == needle:
                    return self._with_pid(p)
        return None

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        q = normalize_name(query)
        if not q:
            return self.get_all()[:limit]
        result: list[dict[str, Any]] = []
        for p in self.products.values():
            if p.get("deleted"):
                continue
            if q in normalize_name(p.get("name") or ""):
                result.append(self._with_pid(p))
                if len(result) >= limit:
                    break
                continue
            for alias in p.get("aliases") or []:
                if q in normalize_name(alias):
                    result.append(self._with_pid(p))
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
            "product_id": product_id,
            "key": data.get("key"),
            "name": (data.get("name") or "").strip(),
            "category": data.get("category"),
            "kind": data.get("kind", "manual"),
            "barcode": (data.get("barcode") or "").strip() or None,
            "brand": data.get("brand"),
            "aliases": list(data.get("aliases") or []),
            "nutrition_per_100g": dict(data.get("nutrition_per_100g") or {}),
            "serving_size_g": data.get("serving_size_g"),
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
            "nutrition_per_100g", "serving_size_g", "default_unit",
            "image_url", "off_last_sync", "deleted", "vectors",
        }
        for k, v in patch.items():
            if k in allowed:
                p[k] = v
        p["updated_at"] = _now()
        await self._save_to_file()
        return self._with_pid(p)

    async def soft_delete(self, product_id: str) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        p["deleted"] = True
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    async def hard_delete(self, product_id: str) -> bool:
        if product_id in self.products:
            del self.products[product_id]
            await self._save_to_file()
            return True
        return False

    async def delete(self, product_id: str, soft: bool = True) -> bool:
        """Единый метод удаления. soft=True — мягкое, soft=False — жёсткое."""
        if soft:
            return await self.soft_delete(product_id)
        return await self.hard_delete(product_id)

    async def restore(self, product_id: str) -> bool:
        p = self.products.get(product_id)
        if not p:
            return False
        p["deleted"] = False
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    # --- Алиасы -------------------------------------------------------

    async def add_alias(self, product_id: str, alias: str) -> dict[str, Any] | None:
        """Добавляет алиас и возвращает продукт.

        Возвращает None, если продукт не найден.
        Бросает ValueError, если алиас уже занят другим продуктом.
        """
        p = self.products.get(product_id)
        if not p:
            return None

        a = (alias or "").strip()
        if not a:
            return self._with_pid(p)

        a_norm = normalize_name(a)
        for other_id, other in self.products.items():
            if other_id == product_id or other.get("deleted"):
                continue
            if normalize_name(other.get("name") or "") == a_norm:
                raise ValueError(
                    f"Алиас '{a}' совпадает с именем продукта "
                    f"'{other.get('name')}' ({other_id})"
                )
            for other_alias in other.get("aliases") or []:
                if normalize_name(other_alias) == a_norm:
                    raise ValueError(
                        f"Алиас '{a}' уже используется продуктом "
                        f"'{other.get('name')}' ({other_id})"
                    )

        aliases = list(p.get("aliases") or [])
        if a in aliases:
            return self._with_pid(p)

        aliases.append(a)
        p["aliases"] = aliases
        p["updated_at"] = _now()
        await self._save_to_file()
        return self._with_pid(p)

    async def remove_alias(self, product_id: str, alias: str) -> dict[str, Any] | None:
        """Убирает алиас и возвращает продукт. None, если продукт не найден."""
        p = self.products.get(product_id)
        if not p:
            return None
        aliases = list(p.get("aliases") or [])
        if alias not in aliases:
            return self._with_pid(p)
        aliases.remove(alias)
        p["aliases"] = aliases
        p["updated_at"] = _now()
        await self._save_to_file()
        return self._with_pid(p)

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

    def list_vectors(self, model_key: str) -> list[tuple[str, list[float]]]:
        """Alias для all_vectors. Используется matcher'ом."""
        return self.all_vectors(model_key)


ingredients_store = IngredientsStore()