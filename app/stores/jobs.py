"""Хранилище async-заданий генерации (in-memory + persistent)."""
from __future__ import annotations

import asyncio
import aiofiles
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from config import DATA_DIR

JOBS_FILE = DATA_DIR / "jobs.json"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class JobsStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.path = JOBS_FILE

    async def load(self) -> None:
        if not self.path.exists():
            return
        try:
            async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                self._jobs = data.get("jobs", {})
            
            # Обрабатываем зависшие задачи при старте
            stale_count = 0
            for job in self._jobs.values():
                if job.get("status") == "pending" and not job.get("interaction_id"):
                    job["status"] = "error"
                    job["error"] = "Прервано перезапуском сервера (нет interaction_id)"
                    job["finished_at"] = _now()
                    stale_count += 1
                    
            if stale_count > 0:
                await self.save()
                
            print(f"[jobs] loaded {len(self._jobs)} jobs ({stale_count} marked as error)")
        except Exception as exc:
            print(f"[jobs] failed to load: {exc}")
            self._jobs = {}

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps({"jobs": self._jobs}, ensure_ascii=False, indent=2))
            tmp.replace(self.path)

    async def create(self, params: dict[str, Any], user_id: str = "system") -> dict[str, Any]:
        job: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "status": "pending",
            "created_at": _now(),
            "finished_at": None,
            "params": params,
            "created": 0,
            "error": None,
            "user_id": user_id,
        }
        async with self._lock:
            self._jobs[job["id"]] = job
        await self.save()
        return dict(job)

    async def update(self, job_id: str, **patch: Any) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.update(patch)
        await self.save()
        return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        return dict(job) if job else None

    def list_pending(self) -> list[dict[str, Any]]:
        return [dict(j) for j in self._jobs.values() if j["status"] == "pending"]

    def list_all(self, max_items: int = 50) -> list[dict[str, Any]]:
        jobs = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
        return [dict(j) for j in jobs[:max_items]]

    async def cleanup(self, max_age_seconds: int = 3600) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        removed = 0
        async with self._lock:
            for jid in list(self._jobs.keys()):
                j = self._jobs[jid]
                fa = j.get("finished_at")
                if not fa:
                    continue
                try:
                    if datetime.fromisoformat(fa) < cutoff:
                        del self._jobs[jid]
                        removed += 1
                except (ValueError, TypeError):
                    continue
        if removed:
            await self.save()
        return removed

jobs_store = JobsStore()
