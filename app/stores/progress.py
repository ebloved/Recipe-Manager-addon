"""Личные данные прогресса (рост, вес, цель).

Файл приватный: API отдаёт записи только владельцу. В журнал действий
значения не пишутся.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import PROGRESS_FILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressStore:
    def __init__(self, path: Path = PROGRESS_FILE) -> None:
        self.path = path
        self.users: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            users = data.get("users", {})
            self.users = users if isinstance(users, dict) else {}
        except Exception as exc:  # noqa: BLE001
            print(f"[progress] failed to load: {exc}")
            self.users = {}

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(
                    {"users": self.users}, ensure_ascii=False, indent=2
                ))
            tmp.replace(self.path)

    def get(self, owner_id: str) -> dict[str, Any] | None:
        item = self.users.get(str(owner_id))
        return dict(item) if item else None

    async def add_weight(
        self,
        owner_id: str,
        *,
        date: str,
        weight_kg: float,
        note: str | None = None,
    ) -> list[dict[str, Any]]:
        record = dict(self.users.get(str(owner_id)) or {})
        weights = list(record.get("weights") or [])
        entry = {
            "id": uuid.uuid4().hex,
            "date": date,
            "weight_kg": weight_kg,
            "note": note,
            "created_at": _now(),
        }
        weights = [item for item in weights if item.get("date") != date]
        weights.append(entry)
        weights.sort(key=lambda item: str(item.get("date") or ""))
        record["weights"] = weights
        record["updated_at"] = _now()
        record.setdefault("created_at", record["updated_at"])
        self.users[str(owner_id)] = record
        await self.save()
        return [dict(item) for item in weights]

    async def delete_weight(self, owner_id: str, entry_id: str) -> list[dict[str, Any]] | None:
        record = self.users.get(str(owner_id))
        if not record:
            return None
        weights = list(record.get("weights") or [])
        remaining = [item for item in weights if item.get("id") != entry_id]
        if len(remaining) == len(weights):
            return None
        record = dict(record)
        record["weights"] = remaining
        record["updated_at"] = _now()
        self.users[str(owner_id)] = record
        await self.save()
        return [dict(item) for item in remaining]

    async def delete(self, owner_id: str) -> bool:
        if str(owner_id) not in self.users:
            return False
        self.users.pop(str(owner_id), None)
        await self.save()
        return True

    async def upsert(self, owner_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = dict(self.users.get(str(owner_id)) or {})
        current.update(patch)
        current["updated_at"] = _now()
        current.setdefault("created_at", current["updated_at"])
        self.users[str(owner_id)] = current
        await self.save()
        return dict(current)


progress_store = ProgressStore()
