"""Шифрование секретов магазинов (Fernet, отдельный ключ от SECRET_KEY)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import SECRET_KEY

LEGACY_SECRET_KEY = "dev-secret-key-change-in-prod"


def _fernet_for(key: str, context: str) -> Fernet:
    digest = hashlib.sha256(f"{key}:{context}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet(context: str = "store-credentials") -> Fernet:
    return _fernet_for(SECRET_KEY, context)


def encrypt(value: str | None, context: str = "store-credentials") -> str | None:
    if not value:
        return None
    return _fernet(context).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str | None, context: str = "store-credentials") -> str | None:
    if not value:
        return None
    try:
        return _fernet(context).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


async def migrate_legacy_secrets() -> int:
    """Перешифровать данные, созданные старым дефолтным SECRET_KEY.

    До v3.11 HA-аддон не задавал SECRET_KEY и использовал публичный
    dev-дефолт. После генерации per-install ключа такие строки нужно
    один раз перешифровать, иначе токены/ключи «пропадут».
    """
    if SECRET_KEY == LEGACY_SECRET_KEY:
        return 0

    from sqlalchemy import select
    from db import SessionLocal
    from stores.db_models import UserLLMConfig, UserStoreCredential

    changed = 0

    def _migrate_value(value: str | None, context: str) -> tuple[str | None, bool]:
        if not value:
            return value, False
        try:
            _fernet_for(SECRET_KEY, context).decrypt(value.encode("utf-8"))
            return value, False  # уже читается текущим ключом
        except Exception:
            pass
        try:
            plain = _fernet_for(LEGACY_SECRET_KEY, context).decrypt(value.encode("utf-8"))
        except Exception:
            return value, False  # не наш формат — не трогаем
        return _fernet_for(SECRET_KEY, context).encrypt(plain).decode("utf-8"), True

    async with SessionLocal() as session:
        rows = (await session.execute(select(UserLLMConfig))).scalars().all()
        for row in rows:
            new, ok = _migrate_value(row.config_enc, "llm-configs")
            if ok:
                row.config_enc = new
                changed += 1

        creds = (await session.execute(select(UserStoreCredential))).scalars().all()
        for row in creds:
            for attr in ("client_id_enc", "client_secret_enc", "access_token_enc", "refresh_token_enc"):
                new, ok = _migrate_value(getattr(row, attr), "store-credentials")
                if ok:
                    setattr(row, attr, new)
                    changed += 1
        await session.commit()

    if changed:
        print(f"[secret] migrated legacy encrypted fields: {changed}")
    return changed
