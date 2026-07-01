import asyncio
import logging
import random

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, UpdateType
from aiogram.types import LinkPreviewOptions
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.db_instance import db
from handlers import user_handlers, menu_handlers, admin_handlers, anon_handlers
from scheduler.jobs import bait_scheduler
from middlewares import ThrottlingMiddleware


async def show_n_scheduler(bot: Bot):
    """
    Фоновый цикл: каждую секунду забирает из БД созревшие Показы N
    и отправляет их пользователям.  Использует частичный индекс по
    (scheduled_at) WHERE sent_at IS NULL — работает быстро при любом
    числе пользователей и переживает рестарты бота.
    """
    from utils.message_sender import send_stored_message
    from aiogram.exceptions import TelegramForbiddenError

    logging.info("[ShowN] Scheduler started")
    while True:
        try:
            pending = await db.get_pending_shows_n(limit=100)
            if pending:
                sent_ids = []
                for row in pending:
                    schedule_id = row["id"]
                    user_id = row["user_id"]
                    delay_minutes = row["delay_minutes"]
                    try:
                        shows = await db.get_shows_n_by_delay(delay_minutes)
                        if not shows:
                            sent_ids.append(schedule_id)
                            continue
                        show = random.choice(shows)
                        ok = await send_stored_message(
                            bot=bot,
                            chat_id=user_id,
                            from_chat_id=show["from_chat_id"],
                            message_id=show["message_id"],
                            msg_json_raw=show.get("message_json"),
                            label=f"show_n#{show['id']}",
                        )
                        if ok:
                            await db.increment_show_n_count(show["id"])
                        sent_ids.append(schedule_id)
                    except TelegramForbiddenError:
                        sent_ids.append(schedule_id)
                    except Exception as e:
                        logging.error(f"[ShowN] Error sending to user {user_id}: {e}")
                        sent_ids.append(schedule_id)
                if sent_ids:
                    await db.mark_show_n_sent_batch(sent_ids)
        except Exception as e:
            logging.error(f"[ShowN] Scheduler loop error: {e}")
        await asyncio.sleep(1)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
    logging.getLogger('apscheduler.jobstores.default').setLevel(logging.WARNING)
    logging.getLogger('apscheduler.scheduler').setLevel(logging.WARNING)
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        )
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    dp.message.middleware(ThrottlingMiddleware(throttle_time=0.5))
    dp.callback_query.middleware(ThrottlingMiddleware(throttle_time=0.5))

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    dp.workflow_data['scheduler'] = scheduler
    dp.workflow_data['bot'] = bot
    
    user_handlers.set_scheduler(scheduler)

    await db.connect()

    from utils.admins import load_admins
    await load_admins()

    asyncio.create_task(show_n_scheduler(bot))
    asyncio.create_task(bait_scheduler(bot))

    dp.include_router(admin_handlers.router)
    dp.include_router(user_handlers.router)
    dp.include_router(menu_handlers.router)
    dp.include_router(anon_handlers.router)

    await bot.delete_webhook(drop_pending_updates=True)
    scheduler.start()

    logging.info("Starting bot...")
    try:
        allowed_updates = [
            UpdateType.MESSAGE,
            UpdateType.CALLBACK_QUERY,
            UpdateType.CHAT_JOIN_REQUEST,
            UpdateType.INLINE_QUERY,
            UpdateType.PRE_CHECKOUT_QUERY,
        ]
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        scheduler.shutdown()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")