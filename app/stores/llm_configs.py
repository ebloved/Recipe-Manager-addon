"""Персональные LLM-конфиги в SQLite (JSON, шифруется Fernet)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select

from db import SessionLocal
from services.secret_store import decrypt, encrypt
from stores.db_models import UserLLMConfig

_CONTEXT = "llm-configs"


class LLMConfigRepository:
    async def load_all(self) -> dict[str, dict[str, Any]]:
        async with SessionLocal() as session:
            result = await session.execute(select(UserLLMConfig))
            rows = result.scalars().all()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            raw = decrypt(row.config_enc, context=_CONTEXT)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out[row.owner_id] = data
        return out

    async def save(self, owner_id: str, config: dict[str, Any]) -> None:
        payload = encrypt(
            json.dumps(config, ensure_ascii=False),
            context=_CONTEXT,
        )
        if not payload:
            return
        async with SessionLocal() as session:
            row = await session.get(UserLLMConfig, owner_id)
            if row is None:
                row = UserLLMConfig(owner_id=owner_id, config_enc=payload)
                session.add(row)
            else:
                row.config_enc = payload
            await session.commit()

    async def delete(self, owner_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                delete(UserLLMConfig).where(UserLLMConfig.owner_id == owner_id)
            )
            await session.commit()
            return bool(result.rowcount)


llm_configs = LLMConfigRepository()
