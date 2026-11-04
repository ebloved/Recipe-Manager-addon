"""Хранилище рецептов: SQLite — источник истины, JSON — снимок/бэкап.

Поведение для остального кода сохранено: синхронные get_all/get/get_by_share_token
работают по in-memory кэшу, async add/update/delete пишут в SQLite.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiofiles
from sqlalchemy import delete, func, select

from config import DATA_DIR, RECIPES_FILE
from db import SessionLocal
from helpers import extract_video_id
from stores.db_models import Recipe, RecipeChange

_UTM_PREFIXES = ("utm_", "fbclid", "gclid", "yclid", "mc_cid", "mc_eid")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _now()


def _canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    path = re.sub(r"/+$", "", parts.path) or "/"
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_UTM_PREFIXES)
    ]
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def _identity(recipe: dict[str, Any]) -> tuple[str, str]:
    """(source, source_id) по текущим правилам v3.1."""
    rid = str(recipe.get("id") or uuid.uuid4().hex)
    source = str(recipe.get("source") or "").strip().lower()
    source_id = str(recipe.get("source_id") or "").strip()
    if source in ("youtube", "web", "manual", "import") and source_id:
        return source, source_id

    url = str(recipe.get("source_url") or "").strip()
    if url:
        video_id = extract_video_id(url)
        if video_id:
            return "youtube", video_id
        return "web", _canonical_url(url)

    return "manual", rid


class RecipeStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.recipes: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Загрузка и миграция JSON → SQLite
    # ------------------------------------------------------------------

    async def load(self) -> None:
        try:
            total = None
            async with SessionLocal() as session:
                total = int(
                    await session.scalar(select(func.count()).select_from(Recipe)) or 0
                )
                if total == 0 and self.path.exists():
                    await self._import_json()
                    return
                rows = (
                    await session.execute(
                        select(Recipe).where(Recipe.deleted_at.is_(None))
                    )
                ).scalars().all()
                self.recipes = [self._row_to_dict(row) for row in rows]
            if total == 0:
                self.recipes = []
            print(f"[recipes] loaded {len(self.recipes)} from SQLite")
        except Exception as exc:  # noqa: BLE001
            print(f"[recipes] SQLite load failed: {exc}; falling back to JSON")
            await self._load_json_legacy()

    async def _load_json_legacy(self) -> None:
        self.recipes = []
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.recipes = data.get("recipes", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[recipes] failed to load JSON: {exc}")

    async def _import_json(self) -> None:
        """Одноразовый импорт recipes.json в SQLite с бэкапом и отчётом."""
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                raw = json.loads(await f.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[recipes] JSON import failed (read): {exc}")
            raise

        items = raw.get("recipes", []) if isinstance(raw, dict) else []
        if not items:
            self.recipes = []
            return

        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%d_%H%M%S")
        backup = backup_dir / f"recipes_pre_sqlite_{stamp}.json"
        try:
            await asyncio.to_thread(shutil.copy2, self.path, backup)
            print(f"[recipes] JSON backup before migration: {backup}")
        except Exception as exc:  # noqa: BLE001
            print(f"[recipes] JSON backup failed: {exc}")

        imported: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        duplicates = 0
        source_counts: dict[str, int] = {}

        async with SessionLocal() as session:
            for raw_recipe in items:
                if not isinstance(raw_recipe, dict):
                    continue
                recipe = dict(raw_recipe)
                rid = str(recipe.get("id") or uuid.uuid4().hex)
                recipe["id"] = rid
                owner = str(recipe.get("owner_id") or "family")
                recipe["owner_id"] = owner
                source, source_id = _identity(recipe)
                recipe["source"] = source
                recipe["source_id"] = source_id
                key = (owner, source, source_id)
                if key in seen:
                    duplicates += 1
                    print(
                        f"[recipes] duplicate identity skipped: "
                        f"{owner}/{source}/{source_id} ({recipe.get('name')})"
                    )
                    continue
                seen.add(key)
                source_counts[source] = source_counts.get(source, 0) + 1

                change = RecipeChange(
                    entity_type="recipe",
                    entity_id=rid,
                    op="upsert",
                    owner_id=owner,
                )
                session.add(change)
                await session.flush()

                row = Recipe(
                    id=rid,
                    owner_id=owner,
                    source=source,
                    source_id=source_id,
                    version=int(recipe.get("version") or 1),
                    revision=change.revision,
                    title=str(recipe.get("name") or ""),
                    payload=recipe,
                    share_token=recipe.get("share_token"),
                    created_at=_parse_dt(recipe.get("created_at")),
                    updated_at=_parse_dt(recipe.get("updated_at")),
                    deleted_at=None,
                )
                session.add(row)
                imported.append(recipe)

            await session.commit()

        self.recipes = imported
        print(
            f"[recipes] migrated JSON -> SQLite: {len(imported)} "
            f"(duplicates skipped: {duplicates}, sources: {source_counts})"
        )

    @staticmethod
    def _row_to_dict(row: Recipe) -> dict[str, Any]:
        recipe = dict(row.payload or {})
        recipe["id"] = row.id
        recipe["owner_id"] = row.owner_id
        recipe["source"] = row.source
        recipe["source_id"] = row.source_id
        return recipe

    # ------------------------------------------------------------------
    # Снимок JSON (бэкап/экспорт; SQLite остаётся истиной)
    # ------------------------------------------------------------------

    async def save(self) -> None:
        async with self._lock:
            await self._write_snapshot()

    async def _write_snapshot(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(
                json.dumps({"recipes": self.recipes}, ensure_ascii=False, indent=2)
            )
        tmp.replace(self.path)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_all(self) -> list[dict[str, Any]]:
        return list(self.recipes)

    def get_by_share_token(self, token: str) -> dict[str, Any] | None:
        return next((r for r in self.recipes if r.get("share_token") == token), None)

    def get(self, recipe_id: str) -> dict[str, Any] | None:
        return next((r for r in self.recipes if r.get("id") == recipe_id), None)

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for r in self.recipes:
            for t in r.get("tags") or []:
                if isinstance(t, str) and t.strip():
                    tags.add(t.strip())
        return sorted(tags)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        recipe = dict(data)
        rid = str(recipe.get("id") or uuid.uuid4().hex)
        recipe["id"] = rid
        recipe.setdefault("owner_id", "family")
        source, source_id = _identity(recipe)
        recipe["source"] = source
        recipe["source_id"] = source_id
        recipe.setdefault("created_at", now.isoformat())
        recipe["updated_at"] = now.isoformat()

        async with self._lock:
            async with SessionLocal() as session:
                existing = (
                    await session.execute(
                        select(Recipe).where(
                            Recipe.owner_id == recipe["owner_id"],
                            Recipe.source == source,
                            Recipe.source_id == source_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None and existing.deleted_at is None:
                    existing_dict = self._row_to_dict(existing)
                    print(
                        f"[recipes] duplicate identity on add: "
                        f"{recipe['owner_id']}/{source}/{source_id}"
                    )
                    return existing_dict

                if existing is not None:
                    # Реанимируем soft-deleted запись.
                    existing.deleted_at = None
                    existing.payload = recipe
                    existing.title = str(recipe.get("name") or "")
                    existing.share_token = recipe.get("share_token")
                    existing.version += 1
                    change = await self._new_change(
                        session, existing.id, "upsert", existing.owner_id
                    )
                    existing.revision = change.revision
                    await session.commit()
                    self.recipes = [r for r in self.recipes if r.get("id") != existing.id]
                    self.recipes.append(recipe)
                    await self._write_snapshot()
                    return recipe

                change = await self._new_change(
                    session, rid, "upsert", recipe["owner_id"]
                )
                row = Recipe(
                    id=rid,
                    owner_id=recipe["owner_id"],
                    source=source,
                    source_id=source_id,
                    version=1,
                    revision=change.revision,
                    title=str(recipe.get("name") or ""),
                    payload=recipe,
                    share_token=recipe.get("share_token"),
                    created_at=_parse_dt(recipe.get("created_at")),
                    updated_at=now,
                )
                session.add(row)
                await session.commit()

            self.recipes.append(recipe)
            await self._write_snapshot()
            return recipe

    async def update(
        self, recipe_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self._lock:
            current = self.get(recipe_id)
            if current is None:
                return None
            updated = {
                **current,
                **patch,
                "updated_at": _now().isoformat(),
            }
            source, source_id = _identity(updated)
            updated["source"] = source
            updated["source_id"] = source_id

            async with SessionLocal() as session:
                row = await session.get(Recipe, recipe_id)
                if row is None or row.deleted_at is not None:
                    return None
                row.payload = updated
                row.title = str(updated.get("name") or "")
                row.share_token = updated.get("share_token")
                row.source = source
                row.source_id = source_id
                row.version += 1
                change = await self._new_change(
                    session, recipe_id, "upsert", row.owner_id
                )
                row.revision = change.revision
                row.updated_at = _now()
                await session.commit()

            for i, r in enumerate(self.recipes):
                if r.get("id") == recipe_id:
                    self.recipes[i] = updated
                    break
            await self._write_snapshot()
            return updated

    async def patch_if_unchanged(
        self,
        recipe_id: str,
        base_hash: str,
        patch: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Применяет патч только если рецепт не изменился с момента чтения."""
        from services.recipe_standard import source_hash

        async with self._lock:
            current = self.get(recipe_id)
            if current is None or source_hash(current) != base_hash:
                return None
            updated = {
                **current,
                **patch,
                "updated_at": _now().isoformat(),
            }
            source, source_id = _identity(updated)
            updated["source"] = source
            updated["source_id"] = source_id

            async with SessionLocal() as session:
                row = await session.get(Recipe, recipe_id)
                if row is None or row.deleted_at is not None:
                    return None
                row.payload = updated
                row.title = str(updated.get("name") or "")
                row.share_token = updated.get("share_token")
                row.source = source
                row.source_id = source_id
                row.version += 1
                change = await self._new_change(
                    session, recipe_id, "upsert", row.owner_id
                )
                row.revision = change.revision
                row.updated_at = _now()
                await session.commit()

            for i, r in enumerate(self.recipes):
                if r.get("id") == recipe_id:
                    self.recipes[i] = updated
                    break
            await self._write_snapshot()
            return updated

    async def list_deleted(self) -> list[dict[str, Any]]:
        """Все soft-deleted рецепты, включая payload и дату удаления."""
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(Recipe)
                    .where(Recipe.deleted_at.isnot(None))
                    .order_by(Recipe.deleted_at.desc())
                )
            ).scalars().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = self._row_to_dict(row)
            item["deleted_at"] = row.deleted_at.isoformat() if row.deleted_at else None
            out.append(item)
        return out

    async def restore(self, recipe_id: str) -> dict[str, Any] | None:
        async with self._lock:
            async with SessionLocal() as session:
                row = await session.get(Recipe, recipe_id)
                if row is None or row.deleted_at is None:
                    return None
                now = _now()
                row.deleted_at = None
                row.version += 1
                change = await self._new_change(
                    session, recipe_id, "upsert", row.owner_id
                )
                row.revision = change.revision
                row.updated_at = now
                await session.commit()
                payload = dict(row.payload or {})
            self.recipes = [r for r in self.recipes if r.get("id") != recipe_id]
            self.recipes.append(payload)
            await self._write_snapshot()
            return payload

    @staticmethod
    def _image_hash(recipe: dict[str, Any]) -> str | None:
        h = str(recipe.get("image_hash") or "").strip()
        if h:
            return h
        url = str(recipe.get("image_url") or "")
        m = re.search(r"/media/([a-f0-9]{64})/", url)
        return m.group(1) if m else None

    async def delete_permanent(self, recipe_id: str) -> bool:
        async with self._lock:
            async with SessionLocal() as session:
                row = await session.get(Recipe, recipe_id)
                if row is None or row.deleted_at is None:
                    return False
                payload = dict(row.payload or {})
                image_hash = self._image_hash(payload)
                await session.delete(row)
                await session.execute(
                    delete(RecipeChange).where(RecipeChange.entity_id == recipe_id)
                )
                await session.commit()

                keep_media = False
                if image_hash:
                    others = (await session.execute(select(Recipe.payload))).scalars().all()
                    keep_media = any(
                        self._image_hash(p or {}) == image_hash for p in others
                    )
            if image_hash and not keep_media:
                from services import media_store
                media_store.delete_image(image_hash)
            self.recipes = [r for r in self.recipes if r.get("id") != recipe_id]
            await self._write_snapshot()
            return True

    async def delete(self, recipe_id: str) -> bool:
        async with self._lock:
            current = self.get(recipe_id)
            if current is None:
                return False
            async with SessionLocal() as session:
                row = await session.get(Recipe, recipe_id)
                if row is None or row.deleted_at is not None:
                    return False
                now = _now()
                row.deleted_at = now
                row.version += 1
                row.share_token = None
                change = await self._new_change(
                    session, recipe_id, "delete", row.owner_id
                )
                row.revision = change.revision
                row.updated_at = now
                await session.commit()

            self.recipes = [r for r in self.recipes if r.get("id") != recipe_id]
            await self._write_snapshot()
            return True

    @staticmethod
    async def _new_change(
        session, entity_id: str, op: str, owner_id: str
    ) -> RecipeChange:
        change = RecipeChange(
            entity_type="recipe",
            entity_id=entity_id,
            op=op,
            owner_id=owner_id,
        )
        session.add(change)
        await session.flush()
        return change


recipe_store = RecipeStore(RECIPES_FILE)
