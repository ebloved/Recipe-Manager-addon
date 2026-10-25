"""Хранилище пользовательских настроек (переопределяет env)."""
import json
from pathlib import Path
from typing import Any
import aiofiles
from config import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"

class SettingsStore:
    def __init__(self):
        self.path = SETTINGS_FILE
        self.data: dict[str, Any] = {}

    async def load(self):
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.loads(await f.read())
            except Exception:
                self.data = {}

    async def save(self):
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(self.data, ensure_ascii=False, indent=2))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    async def set(self, key: str, value: Any):
        self.data[key] = value
        await self.save()

settings_store = SettingsStore()
