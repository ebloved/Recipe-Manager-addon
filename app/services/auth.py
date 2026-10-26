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

    async def load(self):
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                    self.users = data.get("users", {})
            except Exception:
                self.users = {}

    async def save(self):
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(json.dumps({"users": self.users}, ensure_ascii=False, indent=2))

    async def get_or_create(self, google_id: str, email: str, name: str, picture: str) -> dict:
        if google_id not in self.users:
            self.users[google_id] = {
                "id": google_id,
                "email": email,
                "name": name,
                "picture": picture,
                "role": "admin" if not self.users else "user", # Первый юзер - админ
                "created_at": str(uuid.uuid4()),
            }
            await self.save()
        else:
            # Обновляем имя/аватар на случай смены в Google
            self.users[google_id]["name"] = name
            self.users[google_id]["picture"] = picture
            await self.save()
        return self.users[google_id]

users_store = UserStore()
