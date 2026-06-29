"""Отправка сохранённых сообщений: copy_message с fallback на file_id (с entities для премиум-эмодзи) и отключённым превью ссылок."""
import json as _json
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions, MessageEntity

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def convert_entities(entities_raw) -> Optional[list]:
    """Конвертирует сырые dict-сущности в объекты MessageEntity (нужно для премиум-эмодзи в fallback)."""
    if not entities_raw:
        return None
    result = []
    for e in entities_raw:
        if isinstance(e, dict):
            try:
                result.append(MessageEntity.model_validate(e))
            except Exception:
                pass
        elif e is not None:
            result.append(e)
    return result if result else None


def serialize_message(message) -> Optional[dict]:
    """
    aiogram Message -> JSON-совместимый dict для fallback-отправки.
    Дропает Default-сентинелы, datetime -> ISO, Enum -> value, остальное несериализуемое -> str.
    """
    import datetime as _dt
    from enum import Enum as _Enum

    def conv(obj):
        if hasattr(obj, '__class__') and 'Default' in obj.__class__.__name__:
            return None
        if isinstance(obj, _dt.datetime):
            return obj.isoformat()
        if isinstance(obj, _Enum):
            return obj.value
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                val = conv(v)
                if val is not None:
                    result[k] = val
            return result
        if isinstance(obj, (list, tuple, set)):
            return [conv(v) for v in obj]
        try:
            _json.dumps(obj)
            return obj
        except Exception:
            return str(obj)

    try:
        return conv(message.model_dump(exclude_none=True))
    except Exception as e:
        logging.warning(f"serialize_message failed: {e}")
        return None


def parse_msg_json(msg_json_raw) -> Optional[dict]:
    """Парсит message_json из строки или оставляет как dict."""
    if isinstance(msg_json_raw, str):
        try:
            return _json.loads(msg_json_raw)
        except Exception:
            return None
    return msg_json_raw if isinstance(msg_json_raw, dict) else None


def extract_markup(msg_json: Optional[dict], override_markup=None) -> Optional[InlineKeyboardMarkup]:
    """Извлекает inline-клавиатуру из message_json, если не задан override."""
    if override_markup is not None:
        return override_markup
    if not isinstance(msg_json, dict):
        return None
    rm = msg_json.get('reply_markup')
    if isinstance(rm, dict) and rm.get('inline_keyboard'):
        try:
            return InlineKeyboardMarkup.model_validate(rm)
        except Exception:
            return None
    return None


async def send_stored_message(
    bot: Bot,
    chat_id: int,
    from_chat_id: int,
    message_id: int,
    msg_json_raw=None,
    override_markup=None,
    label: str = "message",
) -> bool:
    """
    Отправляет сохранённое сообщение через copy_message с fallback на прямую отправку по file_id.
    Возвращает True при успехе, False при полной неудаче.
    """
    msg_json = parse_msg_json(msg_json_raw)
    markup = extract_markup(msg_json, override_markup)

    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return True
    except Exception as e:
        logging.warning(f"copy_message failed for {label} to {chat_id}: {e}. Trying fallback.")

    if not isinstance(msg_json, dict):
        logging.error(f"No msg_json data for {label} fallback to {chat_id}.")
        return False

    try:
        entities = convert_entities(msg_json.get('entities'))
        caption_entities = convert_entities(msg_json.get('caption_entities'))
        caption = msg_json.get('caption')

        if 'text' in msg_json:
            await bot.send_message(
                chat_id=chat_id,
                text=msg_json['text'],
                entities=entities,
                reply_markup=markup,
                parse_mode=None,
                link_preview_options=_NO_PREVIEW,
            )
        elif 'sticker' in msg_json:
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=msg_json['sticker']['file_id'],
                reply_markup=markup,
            )
        elif 'photo' in msg_json:
            await bot.send_photo(
                chat_id=chat_id,
                photo=msg_json['photo'][-1]['file_id'],
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=markup,
                parse_mode=None,
            )
        elif 'video' in msg_json:
            await bot.send_video(
                chat_id=chat_id,
                video=msg_json['video']['file_id'],
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=markup,
                parse_mode=None,
            )
        elif 'animation' in msg_json:
            await bot.send_animation(
                chat_id=chat_id,
                animation=msg_json['animation']['file_id'],
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=markup,
                parse_mode=None,
            )
        elif 'voice' in msg_json:
            await bot.send_voice(
                chat_id=chat_id,
                voice=msg_json['voice']['file_id'],
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=markup,
                parse_mode=None,
            )
        elif 'document' in msg_json:
            await bot.send_document(
                chat_id=chat_id,
                document=msg_json['document']['file_id'],
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=markup,
                parse_mode=None,
            )
        else:
            logging.error(f"Unsupported message type in {label} fallback for {chat_id}.")
            return False

        return True

    except Exception as fallback_e:
        logging.error(f"Fallback also failed for {label} to {chat_id}: {fallback_e}")
        return False
