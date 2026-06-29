import random
import logging
from aiogram import Bot
from database.db_instance import db
from utils.message_sender import send_stored_message


async def send_show_d_if_needed(bot: Bot, user_id: int) -> bool:
    cooldown_minutes = random.randint(5, 10)

    can_show = await db.can_show_d(user_id, cooldown_minutes)
    if not can_show:
        return False

    show = await db.get_random_show_d_unseen(user_id)
    if not show:
        return False

    try:
        sent = await send_stored_message(
            bot=bot,
            chat_id=user_id,
            from_chat_id=show['from_chat_id'],
            message_id=show['message_id'],
            msg_json_raw=show.get('message_json'),
            label=f"show_d#{show['id']}",
        )
        if sent:
            await db.mark_show_d_sent(user_id)
            await db.mark_show_d_seen(user_id, show['id'])
            await db.increment_show_d_count(show['id'])
        return sent
    except Exception as e:
        logging.error(f"Ошибка при отправке Показ D пользователю {user_id}: {e}")
        return False


async def schedule_show_n_for_user(bot: Bot, user_id: int, delay_minutes: int):
    try:
        shows = await db.get_shows_n_by_delay(delay_minutes)
        if not shows:
            return

        show = random.choice(shows)

        sent = await send_stored_message(
            bot=bot,
            chat_id=user_id,
            from_chat_id=show['from_chat_id'],
            message_id=show['message_id'],
            msg_json_raw=show.get('message_json'),
            label=f"show_n#{show['id']}",
        )
        if sent:
            await db.increment_show_n_count(show['id'])

    except Exception as e:
        logging.error(f"Ошибка при отправке Показ N пользователю {user_id}: {e}")


def should_skip_show_d(context: str) -> bool:
    skip_contexts = ['game', 'payment', 'examples', 'purchase']
    return context in skip_contexts

