import random
from aiogram import Bot
from aiogram.types import Message
from typing import Optional, Dict
import logging


MEDIA_CHANNEL_USERNAME = "rrrreeegh"

_media_cache = []


async def fetch_random_media_from_channel(bot: Bot) -> Optional[Dict[str, str]]:
    try:
        random_message_id = random.randint(1, 100)
        
        try:
            chat_id = f"@{MEDIA_CHANNEL_USERNAME}"
            
            return None
            
        except Exception as e:
            logging.warning(f"Не удалось получить медиа из канала {MEDIA_CHANNEL_USERNAME}: {e}")
            return None
            
    except Exception as e:
        logging.error(f"Ошибка при получении медиа из канала: {e}")
        return None


async def send_random_greeting_media(bot: Bot, chat_id: int, caption: str = None) -> Optional[Message]:
    media = await fetch_random_media_from_channel(bot)
    
    try:
        if media:
            if media['type'] == 'animation':
                return await bot.send_animation(
                    chat_id=chat_id,
                    animation=media['file_id'],
                    caption=caption,
                    parse_mode='HTML'
                )
            elif media['type'] == 'photo':
                return await bot.send_photo(
                    chat_id=chat_id,
                    photo=media['file_id'],
                    caption=caption,
                    parse_mode='HTML'
                )
            elif media['type'] == 'video':
                return await bot.send_video(
                    chat_id=chat_id,
                    video=media['file_id'],
                    caption=caption,
                    parse_mode='HTML'
                )
        else:
            return await bot.send_message(
                chat_id=chat_id,
                text=caption if caption else "✨",
                parse_mode='HTML'
            )
    except Exception as e:
        logging.error(f"Ошибка при отправке медиа: {e}")
        return None


PRESET_MEDIA_IDS = []


def add_preset_media(media_type: str, file_id: str):
    PRESET_MEDIA_IDS.append({'type': media_type, 'file_id': file_id})


def get_random_preset_media() -> Optional[Dict[str, str]]:
    if PRESET_MEDIA_IDS:
        return random.choice(PRESET_MEDIA_IDS)
    return None

