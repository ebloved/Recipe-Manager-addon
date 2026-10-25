"""Фоновые задачи аддона."""
import asyncio
import logging
from stores import recipe_store
from services.active_time import estimate_active_time
from services.activity import is_active
from config import GENERATOR_AUTO_ACTIVE_TIME

logger = logging.getLogger(__name__)

async def active_time_worker():
    if not GENERATOR_AUTO_ACTIVE_TIME:
        logger.info("[bg] active_time_worker disabled (GENERATOR_AUTO_ACTIVE_TIME=false)")
        return

    await asyncio.sleep(60)
    logger.info("[bg] active_time_worker started (2h interval)")
    while True:
        try:
            if is_active(1800):
                await asyncio.sleep(300)
                continue

            recipes = recipe_store.get_all()
            missing = [
                r for r in recipes 
                if r.get("active_time") is None and not r.get("active_time_error")
            ]
            
            if not missing:
                await asyncio.sleep(3600)
                continue
                
            r = missing[0]
            logger.info(f"[bg] estimating '{r.get('name')}' ({len(missing)} left)")
            
            patch = await estimate_active_time(r, force=False, is_bg=True)
            if patch:
                await recipe_store.update(r["id"], patch)
            await asyncio.sleep(7200)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[bg] error: {e}")
            await asyncio.sleep(3600)
