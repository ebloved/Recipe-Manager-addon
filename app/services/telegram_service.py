"""Сервис для отправки сервисных уведомлений в Telegram."""
import asyncio
import logging
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        self.bot: Bot | None = None
        self.chat_id: str | None = None
        self._polling_task: asyncio.Task | None = None

    async def reload(self, token: str | None, chat_id: str | None):
        """Перезапускает бота с новыми настройками."""
        if self._polling_task:
            self._polling_task.cancel()
            self._polling_task = None
            
        if self.bot:
            await self.bot.session.close()
            self.bot = None
            
        if not token:
            logger.info("[telegram] Bot disabled (missing token)")
            return

        try:
            self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            self.chat_id = chat_id
            self._polling_task = asyncio.create_task(self._poll_updates())
            logger.info(f"[telegram] Bot polling started. Target chat_id: {chat_id or 'waiting for message'}")
        except Exception as e:
            logger.error(f"[telegram] Failed to start bot: {e}")
            self.bot = None

    async def _poll_updates(self):
        """Фоновый цикл для получения chat_id (если админ еще не знает его)."""
        offset = 0
        while True:
            try:
                updates = await self.bot.get_updates(offset=offset, timeout=10)
                for u in updates:
                    offset = u.update_id + 1
                    if u.message and u.message.chat:
                        cid = str(u.message.chat.id)
                        
                        # Автопривязка: если chat_id еще не задан, сохраняем его
                        if not self.chat_id:
                            self.chat_id = cid
                            from stores.settings import settings_store
                            await settings_store.set("telegram_chat_id", cid)
                            await self.bot.send_message(chat_id=cid, text="✅ <b>ID успешно привязан!</b>\nТеперь вы будете получать уведомления здесь.")
                            logger.info(f"[telegram] Auto-linked chat_id: {cid}")
                        elif cid != self.chat_id:
                            logger.warning(f"[telegram] Received message from unlinked chat_id: {cid}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[telegram] Polling error: {e}")
                await asyncio.sleep(10)

    async def send(self, text: str):
        if not self.bot or not self.chat_id:
            logger.warning("[telegram] Send skipped (bot/chat_id not configured)")
            return
        try:
            await asyncio.wait_for(self.bot.send_message(chat_id=self.chat_id, text=text), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("[telegram] Send timeout")
        except Exception as e:
            logger.error(f"[telegram] Send error: {e}")

telegram_service = TelegramService()
