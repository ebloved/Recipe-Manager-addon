"""Черновики сгенерированного меню на неделю.

Хранятся отдельно от meal_plan: план попадает в meal_plan только после
явного сохранения. Это позволяет переживать перезагрузку страницы,
перезапуск аддона и продолжать одобрение рецептов.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import MEAL_PLAN_DRAFTS_FILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MealPlanDraftStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path = MEAL_PLAN_DRAFTS_FILE) -> None:
        self.path = path
        self.drafts: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            self.drafts = data.get("drafts", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[meal-plan-drafts] failed to load: {exc}")
            self.drafts = []
        await self.cleanup()
        print(f"[meal-plan-drafts] loaded {len(self.drafts)} drafts")

    async def _save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "drafts": self.drafts,
            }
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def save(self) -> None:
        await self._save()

    def get(self, draft_id: str) -> dict[str, Any] | None:
        draft = next((d for d in self.drafts if d.get("id") == draft_id), None)
        return dict(draft) if draft else None

    def list_for_owner(
        self,
        owner_id: str,
        statuses: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        items = [
            d for d in self.drafts
            if d.get("owner_id") == owner_id
            and (not statuses or d.get("status") in statuses)
        ]
        items.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
        return [dict(d) for d in items[:limit]]

    def latest_active(self, owner_id: str) -> dict[str, Any] | None:
        items = self.list_for_owner(
            owner_id, statuses={"generating", "ready"}, limit=1
        )
        return items[0] if items else None

    async def add(self, draft: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        item = {
            "id": uuid.uuid4().hex,
            "created_at": now,
            "updated_at": now,
            **draft,
        }
        self.drafts.append(item)
        await self._save()
        return dict(item)

    async def update(self, draft_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        for i, draft in enumerate(self.drafts):
            if draft.get("id") != draft_id:
                continue
            updated = {**draft, **patch, "updated_at": _now()}
            self.drafts[i] = updated
            await self._save()
            return dict(updated)
        return None

    async def delete(self, draft_id: str) -> bool:
        before = len(self.drafts)
        self.drafts = [d for d in self.drafts if d.get("id") != draft_id]
        if len(self.drafts) == before:
            return False
        await self._save()
        return True

    async def cleanup(self, max_age_days: int = 14) -> int:
        """Удаляет старые завершённые черновики; активные не трогает."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        keep: list[dict[str, Any]] = []
        removed = 0
        for draft in self.drafts:
            if draft.get("status") in ("saved", "discarded", "error"):
                try:
                    updated = datetime.fromisoformat(draft.get("updated_at") or "")
                    if updated < cutoff:
                        removed += 1
                        continue
                except (TypeError, ValueError):
                    pass
            keep.append(draft)
        if removed:
            self.drafts = keep
            await self._save()
        return removed


meal_plan_drafts_store = MealPlanDraftStore()
