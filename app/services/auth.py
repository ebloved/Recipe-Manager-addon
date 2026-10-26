"""Управление пользователями и OAuth-сессиями."""
import json
import uuid
from pathlib import Path
from typing import Any
import aiofiles
from config import DATA_DIR

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
