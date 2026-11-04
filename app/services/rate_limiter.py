"""Ограничение бесплатных генераций для пользователей без своего ключа."""
import json
import aiofiles
from datetime import date
from config import DATA_DIR

class RateLimiter:
    def __init__(self):
        self.path = DATA_DIR / "rate_limits.json"
        self.data = {}

    async def load(self):
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.loads(await f.read())
            except Exception:
                self.data = {}

    async def can_generate(self, user_id: str, limit: int = 5) -> bool:
        today = str(date.today())
        u = self.data.get(user_id, {"date": today, "count": 0})
        if u["date"] != today:
            u = {"date": today, "count": 0}
        
        if u["count"] >= limit:
            return False
            
        u["count"] += 1
        self.data[user_id] = u
        await self.save()
        return True

    async def save(self):
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(self.data))

rate_limiter = RateLimiter()
