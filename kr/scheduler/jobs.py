import logging
import asyncio
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.db_instance import db
from utils import texts


async def clear_user_show_jobs(scheduler: AsyncIOScheduler, user_id: int):
    """Удаляет все уже запланированные job'ы показов для конкретного пользователя"""
    try:
        shows = await db.get_active_scheduled_shows()
        for show in shows:
            job_id = f"show_{show['id']}_{user_id}"
            try:
                scheduler.remove_job(job_id)
                logging.info(f"Removed existing show job {job_id} for user {user_id}")
            except Exception:
                pass
    except Exception as e:
        logging.error(f"Failed to clear existing show jobs for user {user_id}: {e}")

async def send_scheduled_show(bot: Bot, user_id: int, show_id: int):
    """Отправка запланированного показа пользователю"""
    logging.info(f"🎯 Executing scheduled show job: show_id={show_id}, user_id={user_id}")
    try:
        already_sent = await db.check_show_sent_to_user(user_id, show_id)
        if already_sent:
            logging.info(f"Show {show_id} already sent to user {user_id}. Skipping.")
            return
        
        shows = await db.get_active_scheduled_shows()
        show = next((s for s in shows if s['id'] == show_id), None)
        
        if not show:
            logging.warning(f"Show {show_id} not found or not active.")
            return
        
        user = await db.get_user(user_id)
        if not user:
            logging.warning(f"User {user_id} not found.")
            return
        
        target_audience = show.get('target_audience', 'all')
        user_passed_op = user.get('has_passed_all_ops', False)
        
        logging.info(f"Show {show_id} target: {target_audience}, user passed OP: {user_passed_op}")
        
        if target_audience == 'passed_op' and not user_passed_op:
            logging.info(f"User {user_id} hasn't passed OP. Skipping show {show_id} (target: passed_op).")
            return
        elif target_audience == 'not_passed_op' and user_passed_op:
            logging.info(f"User {user_id} has passed OP. Skipping show {show_id} (target: not_passed_op).")
            return
        
        logging.info(f"Attempting to send show {show_id} to user {user_id} (from_chat_id={show['from_chat_id']}, message_id={show['message_id']})")

        from utils.message_sender import send_stored_message
        sent = await send_stored_message(
            bot=bot,
            chat_id=user_id,
            from_chat_id=show['from_chat_id'],
            message_id=show['message_id'],
            msg_json_raw=show.get('message_json'),
            label=f"scheduled_show#{show_id}",
        )
        if sent:
            await db.mark_show_as_sent(user_id, show_id)
            logging.info(f"✅ Successfully sent show {show_id} to user {user_id} and marked as sent in DB")
        else:
            logging.error(f"❌ Failed to send show {show_id} to user {user_id}: all methods exhausted")
        
    except TelegramForbiddenError:
        logging.warning(f"⚠️ User {user_id} has blocked the bot. Skipping show {show_id}.")
    except Exception as e:
        logging.error(f"❌ Failed to send show {show_id} to user {user_id}: {e}", exc_info=True)


async def schedule_shows_for_user(bot: Bot, scheduler: AsyncIOScheduler, user_id: int):
    """Планирование всех активных показов для пользователя после /start"""
    try:
        shows = await db.get_active_scheduled_shows()
        
        if not shows:
            logging.info(f"No active shows to schedule for user {user_id}")
            return
        
        logging.info(f"Found {len(shows)} active shows to schedule for user {user_id}")
        
        now = datetime.now(scheduler.timezone if scheduler.timezone else timezone.utc)
        logging.info(f"Current time for scheduling: {now}")
        
        scheduled_count = 0
        for show in shows:
            show_id = show['id']
            delay_minutes = show.get('delay_minutes', 5)
            
            already_sent = await db.check_show_sent_to_user(user_id, show_id)
            if already_sent:
                logging.info(f"Show {show_id} already sent to user {user_id}. Skipping scheduling.")
                continue
            
            run_time = now + timedelta(minutes=delay_minutes)
            job_id = f"show_{show_id}_{user_id}"
            
            try:
                scheduler.add_job(
                    send_scheduled_show,
                    'date',
                    run_date=run_time,
                    kwargs={'bot': bot, 'user_id': user_id, 'show_id': show_id},
                    id=job_id,
                    replace_existing=True
                )
                scheduled_count += 1
                logging.info(f"✅ Scheduled show {show_id} for user {user_id} at {run_time} (in {delay_minutes} minutes)")
            except Exception as e:
                logging.error(f"❌ Failed to schedule show {show_id} for user {user_id}: {e}")
        
        logging.info(f"Successfully scheduled {scheduled_count}/{len(shows)} shows for user {user_id}")
        
    except Exception as e:
        logging.error(f"Failed to schedule shows for user {user_id}: {e}")



async def schedule_show_n_for_user(bot: Bot, user_id: int, delay_minutes: int = None):
    """
    Совместимая обёртка: делегирует полное перепланирование в БД.
    Параметр delay_minutes игнорируется — планируются ВСЕ активные показы N.
    """
    try:
        count = await db.schedule_shows_n_for_user(user_id)
        logging.info(f"[ShowN] Scheduled {count} DB entries for user {user_id}")
    except Exception as e:
        logging.error(f"[ShowN] Failed to schedule DB entries for user {user_id}: {e}")

async def cancel_show_n_for_user(user_id: int):
    """Отменяет все неотправленные показы N для пользователя через БД."""
    try:
        await db.cancel_pending_shows_n_for_user(user_id)
    except Exception as e:
        logging.error(f"[ShowN] Failed to cancel pending entries for user {user_id}: {e}")



async def bait_scheduler(bot: Bot):
    """
    Фоновый цикл байт-уведомлений.

    Механика: у каждого байт-поста своё случайное окно «От–До» (минуты). После
    последней активности пользователя каждый пост планируется на случайное время
    в своём окне и отправляется РОВНО ОДИН раз. Любая новая активность
    перевыставляет расписание (старое отменяется) — никакого зацикленного спама.
    """
    logging.info("[Bait] Scheduler started")
    while True:
        try:
            await db.sync_bait_schedules(grace_minutes=1, limit=300)
            due = await db.get_due_baits(limit=100)
            for row in due:
                uid = row['user_id']
                kb = InlineKeyboardBuilder()
                kb.button(text=row.get('button_text') or 'Посмотреть', callback_data="circle:next")
                try:
                    await bot.send_message(uid, row['text'], reply_markup=kb.as_markup())
                except TelegramForbiddenError:
                    pass
                except Exception as e:
                    logging.error(f"[Bait] send to {uid} failed: {e}")
                finally:
                    await db.mark_bait_schedule_sent(uid, row['bait_id'])
                await asyncio.sleep(0.05)
        except Exception as e:
            logging.error(f"[Bait] loop error: {e}")
        await asyncio.sleep(60)