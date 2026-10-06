"""Хранилище профилей генерации рецептов.

- Инициализация из base_profiles.json при первом запуске.
- Детерминированные UUID для базовых профилей.
- CRUD, мягкое удаление, выбор активного профиля.
- Активный профиль хранится в этом же файле (поле active_id).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import BASE_PROFILES_FILE, GEN_PROFILES_FILE


# --- Детерминированные UUID ------------------------------------------------

_BASE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "recipe-manager:gen-profile")


def base_profile_id(key: str) -> str:
    """UUID базового профиля. Стабилен между версиями плагина."""
    return str(uuid.uuid5(_BASE_NAMESPACE, key))


def new_profile_id() -> str:
    """UUID для профиля, созданного пользователем."""
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Значения по умолчанию для constraints --------------------------------

_EMPTY_CONSTRAINTS: dict[str, Any] = {
    "max_calories_per_serving": None,
    "max_active_time_min": None,
    "max_total_time_min": None,
    "avoid_methods": [],
    "prefer_methods": [],
    "avoid_ingredients": [],
    "prefer_ingredients": [],
    "min_protein_per_serving_g": None,
    "max_sugar_per_serving_g": None,
}


def _normalize_constraints(raw: Any) -> dict[str, Any]:
    """Приводит constraints к полному набору полей со значениями по умолчанию."""
    c = dict(_EMPTY_CONSTRAINTS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in c:
                continue
            if k in ("avoid_methods", "prefer_methods", "avoid_ingredients", "prefer_ingredients"):
                c[k] = [str(x).strip() for x in (v or []) if str(x).strip()]
            elif k in ("max_calories_per_serving", "max_active_time_min", "max_total_time_min",
                       "min_protein_per_serving_g", "max_sugar_per_serving_g"):
                if v is None or v == "":
                    c[k] = None
                else:
                    try:
                        c[k] = float(v) if "." in str(v) else int(v)
                    except (TypeError, ValueError):
                        c[k] = None
            else:
                c[k] = v
    return c


# --- Хранилище ------------------------------------------------------------

class GenProfilesStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path = GEN_PROFILES_FILE) -> None:
        self.path = path
        self.profiles: dict[str, dict[str, Any]] = {}
        self.active_id: str | None = None
        self._lock = asyncio.Lock()

    # --- Загрузка / сохранение ----------------------------------------

    async def load(self) -> None:
        if self.path.exists():
            await self._load_from_file()
        else:
            await self._init_from_base()
        added = await self._merge_from_base()
        # Гарантируем, что active_id валиден
        if self.active_id and self.active_id not in self.profiles:
            self.active_id = None
        if self.active_id is None:
            # Автовыбор первого не удалённого
            for p in self.profiles.values():
                if not p.get("deleted"):
                    self.active_id = p["id"]
                    break
            if self.active_id:
                await self._save_to_file()
        print(
            f"[gen_profiles] loaded {len(self.profiles)} profiles"
            + (f" (+{added} from base)" if added else "")
            + (f", active={self.active_id[:8]}…" if self.active_id else ", active=none")
        )

    async def _load_from_file(self) -> None:
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            items = data.get("profiles", [])
            self.profiles = {p["id"]: p for p in items if p.get("id")}
            self.active_id = data.get("active_id")
        except Exception as exc:  # noqa: BLE001
            print(f"[gen_profiles] failed to load: {exc}")
            self.profiles = {}
            self.active_id = None

    async def _init_from_base(self) -> None:
        """Первичная инициализация из base_profiles.json."""
        if not BASE_PROFILES_FILE.exists():
            print(f"[gen_profiles] base file not found: {BASE_PROFILES_FILE}")
            self.profiles = {}
            return
        try:
            async with aiofiles.open(BASE_PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[gen_profiles] failed to init from base: {exc}")
            self.profiles = {}
            return

        now = _now()
        for item in data.get("profiles", []):
            key = item.get("key")
            if not key:
                continue
            profile = self._base_item_to_profile(item, now)
            self.profiles[profile["id"]] = profile
        await self._save_to_file()

    async def _merge_from_base(self) -> int:
        """Добавляет новые профили из base, которых нет локально по key.

        Существующие не трогает — пользователь мог их отредактировать.
        Удалённые не воскрешает.
        """
        if not BASE_PROFILES_FILE.exists():
            return 0
        try:
            async with aiofiles.open(BASE_PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[gen_profiles] failed to read base for merge: {exc}")
            return 0

        existing_keys = {p.get("key") for p in self.profiles.values() if p.get("key")}
        now = _now()
        added = 0
        for item in data.get("profiles", []):
            key = item.get("key")
            if not key or key in existing_keys:
                continue
            profile = self._base_item_to_profile(item, now)
            self.profiles[profile["id"]] = profile
            added += 1

        if added:
            await self._save_to_file()
        return added

    def _base_item_to_profile(self, item: dict[str, Any], now: str) -> dict[str, Any]:
        key = item["key"]
        return {
            "id": base_profile_id(key),
            "key": key,
            "name": item.get("name", ""),
            "description": item.get("description"),
            "icon": item.get("icon") or "🍽",
            "constraints": _normalize_constraints(item.get("constraints")),
            "source": "base",
            "deleted": False,
            "created_at": now,
            "updated_at": now,
        }

    async def _save_to_file(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "active_id": self.active_id,
                "profiles": list(self.profiles.values()),
            }
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def save(self) -> None:
        await self._save_to_file()

    # --- Чтение -------------------------------------------------------

    def get_all(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        items = list(self.profiles.values())
        if not include_deleted:
            items = [p for p in items if not p.get("deleted")]
        # Сначала базовые (source="base"), потом пользовательские.
        # Внутри — по имени.
        return sorted(
            items,
            key=lambda p: (
                0 if p.get("source") == "base" else 1,
                (p.get("name") or "").lower(),
            ),
        )

    def get(self, profile_id: str) -> dict[str, Any] | None:
        return self.profiles.get(profile_id)

    def find_by_key(self, key: str) -> dict[str, Any] | None:
        for p in self.profiles.values():
            if not p.get("deleted") and p.get("key") == key:
                return p
        return None

    def get_active(self) -> dict[str, Any] | None:
        if not self.active_id:
            return None
        p = self.profiles.get(self.active_id)
        if not p or p.get("deleted"):
            return None
        return p

    # --- Изменение ----------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        profile_id = data.get("id") or new_profile_id()

        profile = {
            "id": profile_id,
            "key": data.get("key"),
            "name": (data.get("name") or "").strip(),
            "description": data.get("description"),
            "icon": data.get("icon") or "🍽",
            "constraints": _normalize_constraints(data.get("constraints")),
            "source": data.get("source", "user"),
            "deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        self.profiles[profile_id] = profile
        await self._save_to_file()
        return profile

    async def update(self, profile_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        p = self.profiles.get(profile_id)
        if not p:
            return None

        if "name" in patch and patch["name"] is not None:
            p["name"] = str(patch["name"]).strip()
        if "description" in patch:
            p["description"] = patch["description"]
        if "icon" in patch:
            p["icon"] = patch["icon"] or "🍽"
        if "constraints" in patch:
            p["constraints"] = _normalize_constraints(patch["constraints"])
        if "deleted" in patch:
            p["deleted"] = bool(patch["deleted"])

        p["updated_at"] = _now()
        await self._save_to_file()
        return p

    async def soft_delete(self, profile_id: str) -> bool:
        p = self.profiles.get(profile_id)
        if not p:
            return False
        p["deleted"] = True
        p["updated_at"] = _now()
        # Если удаляем активный — переключаемся на первый доступный
        if self.active_id == profile_id:
            self.active_id = None
            for candidate in self.profiles.values():
                if not candidate.get("deleted"):
                    self.active_id = candidate["id"]
                    break
        await self._save_to_file()
        return True

    async def restore(self, profile_id: str) -> bool:
        p = self.profiles.get(profile_id)
        if not p:
            return False
        p["deleted"] = False
        p["updated_at"] = _now()
        await self._save_to_file()
        return True

    async def hard_delete(self, profile_id: str) -> bool:
        if profile_id not in self.profiles:
            return False
        del self.profiles[profile_id]
        if self.active_id == profile_id:
            self.active_id = None
            for candidate in self.profiles.values():
                if not candidate.get("deleted"):
                    self.active_id = candidate["id"]
                    break
        await self._save_to_file()
        return True

    async def set_active(self, profile_id: str | None) -> bool:
        """Устанавливает активный профиль. None = сбросить."""
        if profile_id is None:
            self.active_id = None
            await self._save_to_file()
            return True
        p = self.profiles.get(profile_id)
        if not p or p.get("deleted"):
            return False
        self.active_id = profile_id
        await self._save_to_file()
        return True


gen_profiles_store = GenProfilesStore()