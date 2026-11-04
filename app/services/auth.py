"""Управление пользователями, OAuth-сессиями и LLM-ключами."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import DATA_DIR, SECRET_KEY
import base64
import hashlib
from cryptography.fernet import Fernet

# Генерируем 32-байтовый ключ из SECRET_KEY (legacy-шифрование users.json)
_LEGACY_SECRET_KEY = "dev-secret-key-change-in-prod"
fernet_key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
cipher = Fernet(fernet_key)
_legacy_fernet_key = base64.urlsafe_b64encode(
    hashlib.sha256(_LEGACY_SECRET_KEY.encode()).digest()
)
legacy_cipher = Fernet(_legacy_fernet_key)

USERS_FILE = DATA_DIR / "users.json"

# Подписанная сессия вместо raw user_id в cookie.
SESSION_COOKIE = "rm_session"
SESSION_MAX_AGE = 7 * 24 * 3600
_session_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="rm-session")


def create_session_token(user_id: str) -> str:
    return _session_serializer.dumps({"uid": user_id})


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _session_serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    return str(uid) if uid else None


class UserStore:
    def __init__(self):
        self.path = USERS_FILE
        self.users: dict[str, dict[str, Any]] = {}
        self.allowed_emails: list[str] = []
        self.llm_configs: dict[str, dict[str, Any]] = {}

    async def load(self):
        raw_text = ""
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    raw_text = await f.read()
                data = json.loads(raw_text)
                self.users = data.get("users", {})
                self.allowed_emails = data.get("allowed_emails", [])
            except Exception:
                self.users = {}
                self.allowed_emails = []

        try:
            from stores.llm_configs import llm_configs
            self.llm_configs = await llm_configs.load_all()
        except Exception as exc:  # noqa: BLE001
            print(f"[auth] LLM configs load failed: {exc}")
            self.llm_configs = {}

        await self._migrate_legacy_llm_configs(raw_text)

    @staticmethod
    def _decrypt_legacy_config(config: dict[str, Any]) -> dict[str, Any]:
        """Расшифровывает старый формат users.json (по полям)."""
        out: dict[str, Any] = {}
        for key, value in config.items():
            if value and ("key" in key or "secret" in key):
                try:
                    out[key] = cipher.decrypt(str(value).encode()).decode()
                except Exception:  # noqa: BLE001
                    try:
                        out[key] = legacy_cipher.decrypt(str(value).encode()).decode()
                    except Exception:  # noqa: BLE001
                        out[key] = ""
            else:
                out[key] = value
        return out

    async def _migrate_legacy_llm_configs(self, raw_text: str) -> None:
        """Переносит llm_config из users.json в SQLite (один раз)."""
        legacy_users = [
            (uid, user.get("llm_config") or {})
            for uid, user in self.users.items()
            if user.get("llm_config")
        ]
        if not legacy_users:
            return

        # Бэкап исходного users.json до удаления ключей.
        try:
            backup_dir = DATA_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"users_pre_llm_db_{stamp}.json"
            backup.write_text(raw_text or json.dumps(
                {"users": self.users, "allowed_emails": self.allowed_emails},
                ensure_ascii=False,
                indent=2,
            ), encoding="utf-8")
            backup.chmod(0o600)
            print(f"[auth] users.json backup: {backup}")
        except Exception as exc:  # noqa: BLE001
            print(f"[auth] users.json backup failed: {exc}")

        try:
            from stores.llm_configs import llm_configs
        except Exception as exc:  # noqa: BLE001
            print(f"[auth] LLM migration skipped: {exc}")
            return

        migrated = 0
        for uid, legacy in legacy_users:
            plain = self._decrypt_legacy_config(legacy)
            existing = self.llm_configs.get(uid) or {}
            merged = {**plain, **existing}  # DB-значения приоритетнее
            try:
                await llm_configs.save(uid, merged)
            except Exception as exc:  # noqa: BLE001
                print(f"[auth] LLM migration failed for {uid}: {exc}")
                continue
            self.llm_configs[uid] = merged
            self.users[uid].pop("llm_config", None)
            migrated += 1

        if migrated:
            await self.save()
            print(f"[auth] migrated LLM keys to SQLite for {migrated} user(s)")

    async def save(self):
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(json.dumps({
                "users": self.users,
                "allowed_emails": self.allowed_emails
            }, ensure_ascii=False, indent=2))

    async def get_or_create(self, google_id: str, email: str, name: str, picture: str) -> dict | None:
        # Если это первый юзер — делаем его админом и добавляем в белый список
        if not self.users:
            self.users[google_id] = {
                "id": google_id, "email": email, "name": name, "picture": picture,
                "role": "admin", "created_at": str(uuid.uuid4()),
            }
            if email not in self.allowed_emails:
                self.allowed_emails.append(email)
            await self.save()
            return self.users[google_id]

        # Если юзер уже есть — обновляем данные и пускаем
        if google_id in self.users:
            self.users[google_id]["name"] = name
            self.users[google_id]["picture"] = picture
            await self.save()
            return self.users[google_id]

        # Если юзера нет, проверяем белый список
        if email in self.allowed_emails:
            self.users[google_id] = {
                "id": google_id, "email": email, "name": name, "picture": picture,
                "role": "user", "created_at": str(uuid.uuid4()),
            }
            await self.save()
            return self.users[google_id]

        # Доступ запрещен
        return None

    async def save_llm_config(self, user_id: str, config: dict):
        if user_id not in self.users:
            return
        existing = dict(self.llm_configs.get(user_id) or {})
        for key, value in config.items():
            if value is None:
                continue
            if value == "":
                existing.pop(key, None)
                continue
            existing[key] = value
        self.llm_configs[user_id] = existing
        from stores.llm_configs import llm_configs
        await llm_configs.save(user_id, existing)
        # В users.json ключей больше не держим.
        if self.users[user_id].pop("llm_config", None) is not None:
            await self.save()

    def get_llm_config(self, user_id: str) -> dict:
        if user_id in self.llm_configs:
            return dict(self.llm_configs[user_id] or {})
        legacy = (self.users.get(user_id) or {}).get("llm_config")
        if legacy:
            return self._decrypt_legacy_config(legacy)
        return {}

    async def add_allowed_email(self, email: str):
        email = email.strip().lower()
        if email and email not in self.allowed_emails:
            self.allowed_emails.append(email)
            await self.save()

    async def remove_user(self, google_id: str):
        if google_id in self.users:
            email = self.users[google_id]["email"]
            if email in self.allowed_emails:
                self.allowed_emails.remove(email)
            del self.users[google_id]
            self.llm_configs.pop(google_id, None)
            try:
                from stores.llm_configs import llm_configs
                await llm_configs.delete(google_id)
            except Exception:  # noqa: BLE001
                pass
            await self.save()


users_store = UserStore()


def get_current_user(request):
    """Возвращает текущего юзера.

    OAuth — из подписанной cookie rm_session.
    HA — фиксированный family-админ.
    """
    test_user = getattr(request.state, "test_mode_user", None)
    if test_user:
        return test_user
    device_user = getattr(request.state, "device_user", None)
    if device_user:
        return device_user
    from config import AUTH_MODE
    if AUTH_MODE == "oauth":
        uid = read_session_token(request.cookies.get(SESSION_COOKIE))
        if uid and uid in users_store.users:
            return users_store.users[uid]
        return None
    return {"id": "family", "role": "admin", "name": "Семья"}
