"""In-memory хранилище async-заданий генерации.

Не персистится: при рестарте аддона все незавершённые задания теряются
(клиент это увидит и может повторить). Завершённые чистятся лениво.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobsStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create(self, params: dict[str, Any]) -> dict[str, Any]:
        job: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "status": "pending",
            "created_at": _now(),
            "finished_at": None,
            "params": params,
            "created": 0,
            "error": None,
        }
        async with self._lock:
            self._jobs[job["id"]] = job
        return dict(job)

    async def update(self, job_id: str, **patch: Any) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.update(patch)
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
        return removed


jobs_store = JobsStore()
