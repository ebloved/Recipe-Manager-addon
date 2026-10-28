"""Управление пользователями и OAuth-сессиями."""
import json
import uuid
from pathlib import Path
from typing import Any
import aiofiles
from config import DATA_DIR, SECRET_KEY
import base64
import hashlib
from cryptography.fernet import Fernet

# Генерируем 32-байтовый ключ из SECRET_KEY
fernet_key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
cipher = Fernet(fernet_key)

USERS_FILE = DATA_DIR / "users.json"

class UserStore:
    def __init__(self):
        self.path = USERS_FILE
        self.users: dict[str, dict[str, Any]] = {}
        self.allowed_emails: list[str] = []

    async def load(self):
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                    self.users = data.get("users", {})
                    self.allowed_emails = data.get("allowed_emails", [])
            except Exception:
                self.users = {}
                self.allowed_emails = []

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
        if user_id in self.users:
            existing = dict(self.users[user_id].get("llm_config") or {})
            for k, v in config.items():
                if v is None:
                    continue
                if v == "":
                    existing.pop(k, None)
                    continue
                if "key" in k or "secret" in k:
                    existing[k] = cipher.encrypt(v.encode()).decode()
                else:
                    existing[k] = v
            self.users[user_id]["llm_config"] = existing
            await self.save()

    def get_llm_config(self, user_id: str) -> dict:
        user = self.users.get(user_id, {})
        conf = user.get("llm_config", {})
        dec_config = {}
        for k, v in conf.items():
            if v and ("key" in k or "secret" in k):
                try:
                    dec_config[k] = cipher.decrypt(v.encode()).decode()
                except Exception:
                    dec_config[k] = ""
            else:
                dec_config[k] = v
        return dec_config

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
            await self.save()

users_store = UserStore()


def get_current_user(request):
    """Возвращает текущего юзера. В HA-режиме — 'family', в OAuth — из куки."""
    test_user = getattr(request.state, "test_mode_user", None)
    if test_user:
        return test_user
    from config import AUTH_MODE
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if session_id and session_id in users_store.users:
            return users_store.users[session_id]
        return None
    return {"id": "family", "role": "admin", "name": "Семья"}
