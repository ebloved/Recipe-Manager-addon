"""Хранилище продуктов (ingredients.json).

Структура файла:
    {
        "schema_version": 1,
        "installation_id": "<uuid4>",
        "products": [
            {
                "product_id": "<uuid4>",
                "barcode": "4607123456789" | null,
                "name": "Греческий йогурт 2%",
                "brand": "Parmalat" | null,
                "image_url": "https://..." | null,
                "category": "Молочные продукты" | null,
                "source": "openfoodfacts" | "manual" | "recipe",
                "nutrition_per_100g": {
                    "calories": 73,
                    "protein": 9,
                    "fat": 2,
                    "carbohydrates": 4,
                    "fiber": null,
                    "sugar": null,
                    "sodium": null
                } | null,
                "serving_size_g": 125 | null,
                "aliases": ["йогурт греческий 2%", "греч. йогурт"],
                "vectors": {
                    "gemini-embedding-001:768": [...],
                    "all-MiniLM-L6-v2:384": [...]
                },
                "created_at": "<iso>",
                "updated_at": "<iso>",
                "deleted": false,
                "installation_id": "<uuid4 создателя>"
            }
        ]
    }
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import INGREDIENTS_FILE


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    """Нормализация имени для поиска алиасов."""
    return (name or "").strip().lower().replace("ё", "е")


class IngredientStore:
    """Хранилище продуктов и их связок."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.schema_version: int = SCHEMA_VERSION
        self.installation_id: str = ""
        self.products: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Загружает файл. Если файла нет — создаёт пустую базу."""
        if not self.path.exists():
            self.installation_id = str(uuid.uuid4())
            self.products = []
            await self.save()
            print(f"[ingredients] created new store, installation_id={self.installation_id}")
            return

        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[ingredients] failed to load: {exc}")
            self.installation_id = str(uuid.uuid4())
            self.products = []
            return

        self.schema_version = int(data.get("schema_version", SCHEMA_VERSION))
        self.installation_id = data.get("installation_id") or str(uuid.uuid4())
        self.products = data.get("products", []) or []

        await self._migrate()

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            payload = {
                "schema_version": self.schema_version,
                "installation_id": self.installation_id,
                "products": self.products,
            }
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def _migrate(self) -> None:
        """Применяет миграции схемы. Сейчас ничего не делает, но структура готова."""
        if self.schema_version == SCHEMA_VERSION:
            return
        # Пример будущей миграции:
        # if self.schema_version == 1:
        #     ... преобразование ...
        #     self.schema_version = 2
        self.schema_version = SCHEMA_VERSION
        await self.save()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, product_id: str) -> dict[str, Any] | None:
        """Возвращает продукт по product_id (включая удалённые)."""
        return next((p for p in self.products if p.get("product_id") == product_id), None)

    def get_active(self, product_id: str) -> dict[str, Any] | None:
        """Возвращает продукт по product_id, если он не удалён."""
        p = self.get(product_id)
        if p and not p.get("deleted"):
            return p
        return None

    def get_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        """Поиск продукта по штрих-коду (только активные)."""
        if not barcode:
            return None
        code = str(barcode).strip()
        return next(
            (p for p in self.products
             if not p.get("deleted") and p.get("barcode") == code),
            None,
        )

    def find_by_name(self, name: str, include_aliases: bool = True) -> dict[str, Any] | None:
        """Точный поиск по имени или алиасу (только активные)."""
        needle = _normalize_name(name)
        if not needle:
            return None

        for p in self.products:
            if p.get("deleted"):
                continue
            if _normalize_name(p.get("name") or "") == needle:
                return p
            if include_aliases:
                for alias in p.get("aliases") or []:
                    if _normalize_name(alias) == needle:
                        return p
        return None

    def list_all(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        if include_deleted:
            return list(self.products)
        return [p for p in self.products if not p.get("deleted")]

    def count(self) -> int:
        return sum(1 for p in self.products if not p.get("deleted"))

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        """Создаёт новый продукт. Генерирует product_id, created_at, updated_at."""
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("'name' is required")

        now = _now()
        product = {
            "product_id": str(uuid.uuid4()),
            "barcode": (str(data["barcode"]).strip() if data.get("barcode") else None),
            "name": name,
            "brand": data.get("brand") or None,
            "image_url": data.get("image_url") or None,
            "category": data.get("category") or None,
            "source": data.get("source") or "manual",
            "nutrition_per_100g": data.get("nutrition_per_100g") or None,
            "serving_size_g": data.get("serving_size_g"),
            "aliases": list(dict.fromkeys(data.get("aliases") or [])),  # дедуп
            "vectors": {},
            "created_at": now,
            "updated_at": now,
            "deleted": False,
            "installation_id": self.installation_id,
        }
        self.products.append(product)
        await self.save()
        return product

    async def update(self, product_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "barcode", "name", "brand", "image_url", "category",
            "source", "nutrition_per_100g", "serving_size_g", "aliases",
        }
        clean = {k: v for k, v in patch.items() if k in allowed}

        for i, p in enumerate(self.products):
            if p.get("product_id") == product_id:
                updated = {**p, **clean, "updated_at": _now()}
                # нормализуем aliases: дедуп + не включаем сам name
                if "aliases" in clean:
                    norm_name = _normalize_name(updated.get("name") or "")
                    seen = set()
                    aliases = []
                    for a in updated.get("aliases") or []:
                        a_norm = _normalize_name(a)
                        if not a_norm or a_norm == norm_name or a_norm in seen:
                            continue
                        seen.add(a_norm)
                        aliases.append(a)
                    updated["aliases"] = aliases
                self.products[i] = updated
                await self.save()
                return updated
        return None

    async def delete(self, product_id: str, soft: bool = True) -> bool:
        """Мягкое удаление: ставит deleted=True, продукт остаётся в файле."""
        for i, p in enumerate(self.products):
            if p.get("product_id") == product_id:
                if soft:
                    self.products[i] = {**p, "deleted": True, "updated_at": _now()}
                else:
                    self.products.pop(i)
                await self.save()
                return True
        return False

    async def restore(self, product_id: str) -> dict[str, Any] | None:
        for i, p in enumerate(self.products):
            if p.get("product_id") == product_id:
                restored = {**p, "deleted": False, "updated_at": _now()}
                self.products[i] = restored
                await self.save()
                return restored
        return None

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------

    async def add_alias(self, product_id: str, alias: str) -> dict[str, Any] | None:
        a = (alias or "").strip()
        if not a:
            return None

        product = self.get_active(product_id)
        if not product:
            return None

        norm_a = _normalize_name(a)
        norm_name = _normalize_name(product.get("name") or "")
        if norm_a == norm_name:
            return product

        # Проверим, не занят ли алиас другим продуктом
        other = self.find_by_name(a)
        if other and other.get("product_id") != product_id:
            raise ValueError(
                f"Алиас '{a}' уже принадлежит продукту '{other.get('name')}'"
            )

        aliases = list(product.get("aliases") or [])
        if a not in aliases:
            aliases.append(a)
        return await self.update(product_id, {"aliases": aliases})

    async def remove_alias(self, product_id: str, alias: str) -> dict[str, Any] | None:
        product = self.get_active(product_id)
        if not product:
            return None
        aliases = [a for a in (product.get("aliases") or []) if a != alias]
        return await self.update(product_id, {"aliases": aliases})

    # ------------------------------------------------------------------
    # Vectors
    # ------------------------------------------------------------------

    def get_vector(self, product_id: str, model_key: str) -> list[float] | None:
        """model_key вида 'gemini-embedding-001:768' или 'all-MiniLM-L6-v2:384'."""
        p = self.get(product_id)
        if not p:
            return None
        return (p.get("vectors") or {}).get(model_key)

    async def set_vector(self, product_id: str, model_key: str, vector: list[float]) -> None:
        for i, p in enumerate(self.products):
            if p.get("product_id") == product_id:
                vectors = dict(p.get("vectors") or {})
                vectors[model_key] = list(vector)
                self.products[i] = {**p, "vectors": vectors, "updated_at": _now()}
                await self.save()
                return

    def list_vectors(self, model_key: str) -> list[tuple[str, list[float]]]:
        """Возвращает [(product_id, vector), ...] для активных продуктов с этим вектором."""
        out = []
        for p in self.products:
            if p.get("deleted"):
                continue
            v = (p.get("vectors") or {}).get(model_key)
            if v:
                out.append((p["product_id"], v))
        return out

    # ------------------------------------------------------------------
    # Merge (для синхронизации с GitHub)
    # ------------------------------------------------------------------

    def merge_from(
        self,
        other: dict[str, Any],
        strategy: str = "last-write-wins",
    ) -> dict[str, int]:
        """Мержит другой ingredients.json в текущий. Возвращает статистику.

        Приоритет сопоставления продуктов:
          1. Совпадение product_id.
          2. Совпадение barcode.
          3. Совпадение нормализованного name (или алиасов).

        strategy:
          - 'last-write-wins'  — свежий updated_at перезаписывает старый.
          - 'local-wins'       — локальные записи не перезаписываются.
          - 'remote-wins'      — удалённые записи перезаписывают локальные.
        """
        stats = {"added": 0, "updated": 0, "merged_aliases": 0, "skipped": 0, "conflicts": 0}

        remote_products = (other or {}).get("products", []) or []
        for rp in remote_products:
            if not isinstance(rp, dict):
                continue

            local = self._find_match(rp)
            if local is None:
                # добавим как новый, сохранив product_id от удалённого
                self.products.append(rp)
                stats["added"] += 1
                continue

            # нашли совпадение
            if local.get("product_id") == rp.get("product_id"):
                # полное совпадение — просто мерж по updated_at
                if self._should_overwrite(local, rp, strategy):
                    self.products[self.products.index(local)] = {**local, **rp}
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            else:
                # совпало по barcode или name — но product_id разные
                # оставляем тот, у которого updated_at свежее, ко второму дописываем алиасы
                if self._should_overwrite(local, rp, strategy):
                    merged_aliases = self._merge_aliases(local, rp)
                    self.products[self.products.index(local)] = {
                        **local,
                        **rp,
                        "aliases": merged_aliases,
                    }
                    stats["updated"] += 1
                    if len(merged_aliases) > len(local.get("aliases") or []):
                        stats["merged_aliases"] += 1
                else:
                    # локальный свежее — но алиасы удалённого всё равно подберём
                    merged_aliases = self._merge_aliases(local, rp)
                    if merged_aliases != (local.get("aliases") or []):
                        idx = self.products.index(local)
                        self.products[idx] = {**local, "aliases": merged_aliases}
                        stats["merged_aliases"] += 1

        return stats

    def _find_match(self, remote_product: dict[str, Any]) -> dict[str, Any] | None:
        # 1. product_id
        pid = remote_product.get("product_id")
        if pid:
            p = self.get(pid)
            if p:
                return p
        # 2. barcode
        bc = remote_product.get("barcode")
        if bc:
            p = self.get_by_barcode(str(bc))
            if p:
                return p
        # 3. name (включая алиасы)
        name = remote_product.get("name")
        if name:
            p = self.find_by_name(name)
            if p:
                return p
        return None

    @staticmethod
    def _should_overwrite(local: dict[str, Any], remote: dict[str, Any], strategy: str) -> bool:
        if strategy == "local-wins":
            return False
        if strategy == "remote-wins":
            return True
        # last-write-wins
        local_ts = local.get("updated_at") or ""
        remote_ts = remote.get("updated_at") or ""
        return remote_ts > local_ts

    @staticmethod
    def _merge_aliases(local: dict[str, Any], remote: dict[str, Any]) -> list[str]:
        """Объединяет алиасы + добавляет имена обоих как алиасы."""
        aliases: list[str] = []
        seen: set[str] = set()

        def add(x: str | None) -> None:
            if not x:
                return
            norm = _normalize_name(x)
            if not norm or norm in seen:
                return
            seen.add(norm)
            aliases.append(x)

        for a in (local.get("aliases") or []):
            add(a)
        for a in (remote.get("aliases") or []):
            add(a)
        # имена — тоже алиасы друг друга
        if remote.get("name") and remote.get("name") != local.get("name"):
            add(remote["name"])
        return aliases

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(self) -> dict[str, Any]:
        """Возвращает весь файл как dict для синка/бэкапа."""
        return {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "products": self.products,
        }


# Синглтон
ingredients_store = IngredientStore(INGREDIENTS_FILE)