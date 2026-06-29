
import asyncio
import io
import logging
from typing import Union

from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.filters import Command, StateFilter, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, User, BufferedInputFile

from config import ADMIN_IDS
from database.db_instance import db
from utils.texts import extract_icon_from_message
from utils.message_sender import send_stored_message
from keyboards.inline_keyboards import (
    get_admin_main_menu_kb, get_admin_op_menu_kb,
    get_admin_check_type_kb, get_admin_channel_list_kb, get_admin_cancel_kb,
    get_ad_links_list_kb, get_ad_link_stats_kb, get_admin_tasks_menu_kb, get_admin_tasks_list_kb,
    get_admin_premium_target_kb, get_admin_subgram_mode_kb,
    get_admin_greetings_menu_kb, get_admin_greetings_list_kb, get_admin_shows_menu_kb,
    get_admin_shows_list_kb, get_admin_show_target_kb,
    get_admin_services_menu_kb, get_admin_service_edit_kb,
    get_admin_circles_menu_kb, get_admin_bait_circles_list_kb, get_admin_bait_gender_kb,
    get_admin_bait_menu_kb, get_admin_bait_msg_list_kb,
    get_admin_reports_list_kb, get_admin_report_actions_kb,
    get_circle_moderation_done_kb,
    get_admin_settings_menu_kb, get_admin_settings_list_kb, get_admin_setting_edit_kb,
)
from states.game_states import Admin
from utils import app_config as appcfg

_SETTING_KIND = {s['key']: s['kind'] for s in appcfg.ECONOMY_SETTINGS}
_SETTING_KIND.update({s['key']: 'text' for s in appcfg.TEXT_SETTINGS})
_SETTING_LABEL = {s['key']: s['label'] for s in appcfg.ECONOMY_SETTINGS}
_SETTING_LABEL.update({s['key']: s['label'] for s in appcfg.TEXT_SETTINGS})
_TEXT_KEYS = {s['key'] for s in appcfg.TEXT_SETTINGS}

router = Router()

class IsAdmin(Filter):
    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        return event.from_user.id in ADMIN_IDS


_CLUTTER_DELETE_STATES = {
    Admin.add_whitelist_user_id.state, Admin.select_whitelist_user_for_exclusion.state,
    Admin.greeting_add_button.state, Admin.add_channel_name.state, Admin.add_channel_url.state,
    Admin.add_channel_chat_id.state,
    Admin.add_ad_link_name.state, Admin.add_task_name.state, Admin.add_task_reward.state,
    Admin.add_task_url.state, Admin.add_task_chat_id.state, Admin.add_show_delay.state,
    Admin.add_special_button_text.state, Admin.add_special_button_url.state, Admin.add_show_n_delay.state,
    Admin.edit_service_value.state, Admin.edit_op_limit_value.state, Admin.add_bait_circle_video.state,
    Admin.add_bait_circle_name.state,
    Admin.add_bait_circle_username.state, Admin.add_bait_message_text.state, Admin.add_bait_message_button.state,
    Admin.add_bait_message_delay.state,
    Admin.edit_setting_value.state, Admin.broadcast_add_button.state,
}


class AdminClutterMiddleware(BaseMiddleware):
    """Удаляет сообщение-ввод админа в текстовых шагах мастеров (анти-засор чата)."""
    async def __call__(self, handler, event, data):
        state = data.get('state')
        pre_state = None
        if state is not None:
            try:
                pre_state = await state.get_state()
            except Exception:
                pre_state = None
        result = await handler(event, data)
        if (pre_state in _CLUTTER_DELETE_STATES and isinstance(event, Message)
                and event.from_user and event.from_user.id in ADMIN_IDS):
            try:
                await event.delete()
            except Exception:
                pass
        return result


router.message.middleware(AdminClutterMiddleware())


async def _wiz_edit(message: Message, state: FSMContext, text: str, reply_markup=None):
    """«Единое окно» мастера: на каждом шаге редактирует одно сообщение бота, а не шлёт новое (ID в FSM _wiz_msg)."""
    data = await state.get_data()
    wiz = data.get('_wiz_msg')
    if wiz:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=wiz, text=text, reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(_wiz_msg=sent.message_id)

@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message):
    open_reports = await db.count_open_reports()
    await message.answer("🛠 <b>Админ-панель Кружок-бота</b>", reply_markup=get_admin_main_menu_kb(open_reports))

@router.callback_query(F.data == "admin:main_menu", IsAdmin())
async def cq_admin_main_menu(query: CallbackQuery, state: FSMContext):
    await state.clear()
    open_reports = await db.count_open_reports()
    try:
        await query.message.edit_text("🛠 <b>Админ-панель Кружок-бота</b>", reply_markup=get_admin_main_menu_kb(open_reports))
    except Exception:
        await query.message.answer("🛠 <b>Админ-панель Кружок-бота</b>", reply_markup=get_admin_main_menu_kb(open_reports))


@router.callback_query(F.data == "admin:op_management", IsAdmin())
async def cq_op_management(query: CallbackQuery):
    await query.message.edit_text(
        "Меню управления Обязательной Подпиской (ОП):",
        reply_markup=get_admin_op_menu_kb()
    )


@router.callback_query(F.data == "admin:whitelist", IsAdmin())
async def cq_whitelist_menu(query: CallbackQuery):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить ID в вайтлист", callback_data="admin:wl:add"))
    builder.row(InlineKeyboardButton(text="🗂 Исключения каналов", callback_data="admin:wl:channels"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:op_management"))
    await query.message.edit_text("Раздел: Вайтлист админов", reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin:wl:add", IsAdmin())
async def cq_wl_add_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_whitelist_user_id)
    await query.message.edit_text("Отправьте Telegram ID пользователя, которого нужно добавить в вайтлист:",
                                  reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_whitelist_user_id, F.text, IsAdmin())
async def cq_wl_add_process(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        await db.add_whitelist_user(user_id)
        await state.clear()
        await message.answer("✅ Пользователь добавлен в вайтлист.")
        await message.answer("Раздел: Вайтлист админов", reply_markup=(await _wl_menu_kb()))
    except ValueError:
        await message.answer("❌ Ошибка. Введите корректный числовой Telegram ID.")


async def _wl_menu_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить ID в вайтлист", callback_data="admin:wl:add"))
    builder.row(InlineKeyboardButton(text="🗂 Исключения каналов", callback_data="admin:wl:channels"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:op_management"))
    return builder.as_markup()


@router.callback_query(F.data == "admin:wl:channels", IsAdmin())
async def cq_wl_channels(query: CallbackQuery, state: FSMContext):
    await state.clear()
    channels = await db.get_all_admin_channels_ordered()
    globals_ex = await db.get_whitelist_global_exclusions()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    if not channels:
        builder.row(InlineKeyboardButton(text="Каналов пока нет", callback_data="noop"))
    else:
        for ch in channels:
            is_excluded = ch['id'] in globals_ex
            mark = "❌ Выкл" if is_excluded else "✅ Вкл"
            builder.row(InlineKeyboardButton(text=f"{ch['name']} — {mark}", callback_data=f"admin:wl:toggle_global:{ch['id']}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:whitelist"))
    await query.message.edit_text("Исключения каналов (для пользователей из вайтлиста):", reply_markup=builder.as_markup())


@router.message(Admin.select_whitelist_user_for_exclusion, F.text, IsAdmin())
async def cq_wl_channels_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Ошибка. Введите корректный числовой Telegram ID.")
        return
    await state.update_data(wl_user_id=user_id)
    channels = await db.get_all_admin_channels()
    exclusions = await db.get_whitelist_exclusions(user_id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    if not channels:
        builder.row(InlineKeyboardButton(text="Каналов нет", callback_data="noop"))
    else:
        for ch in channels:
            is_excluded = ch['id'] in exclusions
            mark = "❌" if is_excluded else "✅"
            builder.row(InlineKeyboardButton(
                text=f"{mark} {ch['name']}", callback_data=f"admin:wl:toggle:{ch['id']}"
            ))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:whitelist"))
    await message.answer("Выберите каналы, которые НЕ будут показываться вайтлист-пользователю:",
                         reply_markup=builder.as_markup())
    await state.set_state(Admin.wl_toggle)


@router.callback_query(Admin.wl_toggle, F.data.startswith("admin:wl:toggle:"), IsAdmin())
async def cq_wl_toggle(query: CallbackQuery, state: FSMContext):
    try:
        ch_id = int(query.data.split(":")[-1])
    except Exception:
        await query.answer("Ошибка в данных кнопки.", show_alert=True)
        return
    data = await state.get_data()
    user_id = data.get('wl_user_id')
    if not user_id:
        await query.answer("Сессия истекла. Зайдите заново.", show_alert=True)
        return
    toggled_to_excluded = await db.toggle_whitelist_exclusion(user_id, ch_id)
    await query.answer("Исключено" if toggled_to_excluded else "Включено", show_alert=False)
    channels = await db.get_all_admin_channels()
    exclusions = await db.get_whitelist_exclusions(user_id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for ch in channels:
        is_excluded = ch['id'] in exclusions
        mark = "❌" if is_excluded else "✅"
        builder.row(InlineKeyboardButton(text=f"{mark} {ch['name']}", callback_data=f"admin:wl:toggle:{ch['id']}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:whitelist"))
    try:
        await query.message.edit_reply_markup(reply_markup=builder.as_markup())
    except Exception:
        await query.message.edit_text("Обновление списка...", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin:wl:toggle_global:"), IsAdmin())
async def cq_wl_toggle_global(query: CallbackQuery):
    try:
        ch_id = int(query.data.split(":")[-1])
    except Exception:
        await query.answer("Ошибка в данных кнопки.", show_alert=True)
        return
    toggled = await db.toggle_whitelist_global_exclusion(ch_id)
    await query.answer("Отключено для вайтлиста" if toggled else "Включено для вайтлиста", show_alert=False)
    channels = await db.get_all_admin_channels_ordered()
    globals_ex = await db.get_whitelist_global_exclusions()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for ch in channels:
        is_excluded = ch['id'] in globals_ex
        mark = "❌ Выкл" if is_excluded else "✅ Вкл"
        builder.row(InlineKeyboardButton(text=f"{ch['name']} — {mark}", callback_data=f"admin:wl:toggle_global:{ch['id']}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:whitelist"))
    try:
        await query.message.edit_reply_markup(reply_markup=builder.as_markup())
    except Exception:
        await query.message.edit_text("Исключения каналов (для пользователей из вайтлиста):", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin:greetings_menu", IsAdmin())
async def cq_greetings_menu(query: CallbackQuery):
    await query.message.edit_text(
        "👋 **Управление приветствиями**\n\n"
        "Приветствия — это сообщения, которые бот случайным образом выбирает и отправляет новому пользователю при старте (команда /start) перед основным приветственным сообщением.",
        reply_markup=get_admin_greetings_menu_kb()
    )


@router.callback_query(F.data == "admin:add_greeting", IsAdmin())
async def cq_add_greeting_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(adding_greeting=True, gr_buttons=[], gr_edit_id=None)
    await state.set_state(Admin.add_greeting_message)
    await query.message.edit_text(
        "Перешлите или отправьте сюда сообщение для приветствия. "
        "Можно пересылать из каналов, от других ботов или пользователей.\n\n"
        "Поддерживаются фото, гифки, видео, стикеры и обычный текст.\n\n"
        "После этого можно будет добавить кнопки-ссылки и посмотреть предпросмотр.",
        reply_markup=get_admin_cancel_kb()
    )


@router.message(Admin.add_greeting_message, ~F.text.startswith("/"))
async def process_add_greeting_message(message: Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        adding_show_d = user_data.get('adding_show_d', False)
        adding_show_n = user_data.get('adding_show_n', False)
        show_n_delay = user_data.get('show_n_delay')
        
        from_chat_id = message.forward_from_chat.id if message.forward_from_chat else message.chat.id
        message_id = message.forward_from_message_id if message.forward_from_message_id else message.message_id
        
        import json
        import datetime as _dt
        from enum import Enum as _Enum

        raw_dump = message.model_dump(exclude_none=True)

        def to_jsonable(obj):
            if hasattr(obj, '__class__') and 'Default' in obj.__class__.__name__:
                return None
            if isinstance(obj, _dt.datetime):
                return obj.isoformat()
            if isinstance(obj, _Enum):
                return obj.value
            if isinstance(obj, dict):
                result = {}
                for k, v in obj.items():
                    val = to_jsonable(v)
                    if val is not None:
                        result[k] = val
                return result
            if isinstance(obj, (list, tuple, set)):
                return [to_jsonable(v) for v in obj]
            try:
                json.dumps(obj)
                return obj
            except Exception:
                return str(obj)

        message_json = to_jsonable(raw_dump)

        if adding_show_d:
            await db.add_show_d(
                from_chat_id=from_chat_id,
                message_id=message_id,
                message_json=message_json
            )
            await state.clear()
            await message.answer("✅ Реклама в ленте добавлена!")
            from keyboards.inline_keyboards import get_admin_shows_d_list_kb
            shows = await db.get_all_shows_d()
            await message.answer(f"⚡️ <b>Реклама в ленте — список ({len(shows)})</b>", reply_markup=get_admin_shows_d_list_kb(shows))
        
        elif adding_show_n:
            await db.add_show_n(
                from_chat_id=from_chat_id,
                message_id=message_id,
                delay_minutes=show_n_delay,
                message_json=message_json
            )
            await state.clear()
            await message.answer("✅ Реклама по таймеру добавлена!")
            from keyboards.inline_keyboards import get_admin_shows_n_list_kb
            shows = await db.get_all_shows_n()
            await message.answer(f"📺 <b>Реклама по таймеру — список ({len(shows)})</b>", reply_markup=get_admin_shows_n_list_kb(shows))
        
        else:
            from keyboards.inline_keyboards import get_admin_greeting_compose_kb
            await state.update_data(
                gr_from_chat_id=from_chat_id,
                gr_message_id=message_id,
                gr_message_json=message_json,
            )
            await state.set_state(Admin.greeting_compose)
            data = await state.get_data()
            buttons = data.get('gr_buttons', [])
            await message.answer(
                _greet_compose_text(buttons, bool(data.get('gr_edit_id'))),
                reply_markup=get_admin_greeting_compose_kb(len(buttons), bool(data.get('gr_edit_id'))),
            )

    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при добавлении: {e}", parse_mode=None)


@router.callback_query(F.data == "admin:list_greetings", IsAdmin())
async def cq_list_greetings(query: CallbackQuery):
    greetings = await db.get_all_greetings()
    text = "Список всех приветок:" if greetings else "Приветок пока нет."
    await query.message.edit_text(text, reply_markup=get_admin_greetings_list_kb(greetings))


@router.callback_query(F.data.startswith("admin:delete_greet:"), IsAdmin())
async def cq_delete_greeting(query: CallbackQuery):
    greeting_id = int(query.data.split(":")[2])
    await db.delete_greeting(greeting_id)
    await query.answer("Приветка удалена!", show_alert=True)
    await cq_list_greetings(query)


@router.callback_query(F.data.startswith("admin:preview_greet:"), IsAdmin())
async def cq_preview_greeting(query: CallbackQuery, bot: Bot):
    greeting_id = int(query.data.split(":")[2])
    greetings = await db.get_all_greetings()
    greeting = next((g for g in greetings if g['id'] == greeting_id), None)

    if not greeting:
        await query.answer("Приветка не найдена.", show_alert=True)
        return

    sent = await send_stored_message(
        bot=bot,
        chat_id=query.from_user.id,
        from_chat_id=greeting['from_chat_id'],
        message_id=greeting['message_id'],
        msg_json_raw=greeting.get('message_json'),
        label=f"preview_greet#{greeting_id}",
    )
    if sent:
        await query.answer()
    else:
        await query.answer("Не удалось показать приветку.", show_alert=True)



def _greet_compose_text(buttons: list, is_edit: bool = False) -> str:
    head = "✏️ <b>Редактирование приветки</b>" if is_edit else "👋 <b>Сообщение принято.</b>"
    lines = [head, ""]
    if buttons:
        lines.append(f"Кнопки ({len(buttons)}):")
        for b in buttons:
            lines.append(f"• {b['text']} → {b['url']}")
    else:
        lines.append("Кнопок пока нет.")
    lines.append("")
    lines.append("Добавьте кнопки-ссылки (по желанию), посмотрите предпросмотр и нажмите «💾 Сохранить».")
    return "\n".join(lines)


def _parse_buttons_from_json(message_json) -> list:
    """Достаёт url-кнопки из reply_markup сохранённого сообщения (для редактирования)."""
    from utils.message_sender import parse_msg_json
    mj = parse_msg_json(message_json)
    out = []
    rm = mj.get('reply_markup') if isinstance(mj, dict) else None
    if isinstance(rm, dict):
        for row in rm.get('inline_keyboard', []):
            for b in row:
                if isinstance(b, dict) and b.get('url'):
                    out.append({
                        'text': b.get('text', ''),
                        'url': b['url'],
                        'icon_emoji_id': b.get('icon_custom_emoji_id'),
                    })
    return out


async def _show_greet_compose(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_greeting_compose_kb
    data = await state.get_data()
    buttons = data.get('gr_buttons', [])
    is_edit = bool(data.get('gr_edit_id'))
    await query.message.edit_text(
        _greet_compose_text(buttons, is_edit),
        reply_markup=get_admin_greeting_compose_kb(len(buttons), is_edit),
    )


@router.callback_query(F.data.startswith("admin:edit_greet:"), IsAdmin())
async def cq_edit_greeting(query: CallbackQuery, state: FSMContext):
    from utils.message_sender import parse_msg_json
    greeting_id = int(query.data.split(":")[2])
    greeting = await db.get_greeting_by_id(greeting_id)
    if not greeting:
        await query.answer("Приветка не найдена.", show_alert=True)
        return
    await state.clear()
    await state.update_data(
        adding_greeting=True,
        gr_edit_id=greeting_id,
        gr_from_chat_id=greeting['from_chat_id'],
        gr_message_id=greeting['message_id'],
        gr_message_json=parse_msg_json(greeting.get('message_json')),
        gr_buttons=_parse_buttons_from_json(greeting.get('message_json')),
    )
    await state.set_state(Admin.greeting_compose)
    await _show_greet_compose(query, state)
    await query.answer()


@router.callback_query(F.data == "admin:greet_add_btn", IsAdmin())
async def cq_greet_add_btn(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_broadcast_cancel_kb
    data = await state.get_data()
    if len(data.get('gr_buttons', [])) >= _BC_MAX_BUTTONS:
        await query.answer(f"Максимум {_BC_MAX_BUTTONS} кнопок.", show_alert=True)
        return
    await state.set_state(Admin.greeting_add_button)
    await query.message.edit_text(
        "Отправьте кнопку в формате:\n\n"
        "<code>Текст кнопки | https://ссылка</code>\n\n"
        "💡 Премиум-эмодзи в начале текста станет иконкой кнопки.",
        reply_markup=get_admin_broadcast_cancel_kb(),
    )
    await query.answer()


@router.message(Admin.greeting_add_button, F.text)
async def process_greet_add_button(message: Message, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_greeting_compose_kb, get_admin_broadcast_cancel_kb
    clean_text, emoji_id = extract_icon_from_message(message)
    raw = (clean_text or "").strip()
    sep = '|' if '|' in raw else (' - ' if ' - ' in raw else None)
    if not sep:
        await message.answer(
            "❌ Не вижу разделитель. Формат: <code>Текст | https://ссылка</code>",
            reply_markup=get_admin_broadcast_cancel_kb(),
        )
        return
    label, url = raw.split(sep, 1)
    label, url = label.strip(), url.strip()
    if not label or not url.startswith(("http://", "https://")):
        await message.answer(
            "❌ Текст пустой или ссылка не начинается с http:// или https://. Попробуйте снова.",
            reply_markup=get_admin_broadcast_cancel_kb(),
        )
        return
    data = await state.get_data()
    buttons = list(data.get('gr_buttons', []))
    buttons.append({'text': label, 'url': url, 'icon_emoji_id': emoji_id})
    await state.update_data(gr_buttons=buttons)
    await state.set_state(Admin.greeting_compose)
    await message.answer(
        _greet_compose_text(buttons, bool(data.get('gr_edit_id'))),
        reply_markup=get_admin_greeting_compose_kb(len(buttons), bool(data.get('gr_edit_id'))),
    )


@router.callback_query(F.data == "admin:greet_clear_btns", IsAdmin())
async def cq_greet_clear_btns(query: CallbackQuery, state: FSMContext):
    await state.update_data(gr_buttons=[])
    await _show_greet_compose(query, state)
    await query.answer("Кнопки убраны.")


@router.callback_query(F.data == "admin:greet_replace_msg", IsAdmin())
async def cq_greet_replace_msg(query: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.add_greeting_message)
    await query.message.edit_text(
        "Перешлите или отправьте новое сообщение для приветки.\n"
        "Кнопки сохранятся.",
        reply_markup=get_admin_cancel_kb(),
    )
    await query.answer()


@router.callback_query(F.data == "admin:greet_preview", IsAdmin())
async def cq_greet_preview(query: CallbackQuery, state: FSMContext, bot: Bot):
    from keyboards.inline_keyboards import build_broadcast_markup
    data = await state.get_data()
    if not data.get('gr_message_id'):
        await query.answer("Сессия истекла, начните заново.", show_alert=True)
        return
    markup = build_broadcast_markup(data.get('gr_buttons', []))
    sent = await send_stored_message(
        bot=bot,
        chat_id=query.from_user.id,
        from_chat_id=data['gr_from_chat_id'],
        message_id=data['gr_message_id'],
        msg_json_raw=data.get('gr_message_json'),
        override_markup=markup,
        label="greet_preview",
    )
    if not sent:
        await query.answer("Не удалось показать предпросмотр.", show_alert=True)
        return
    await _show_greet_compose(query, state)
    await query.answer("Это предпросмотр ☝️")


@router.callback_query(F.data == "admin:greet_save", IsAdmin())
async def cq_greet_save(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import build_broadcast_markup
    data = await state.get_data()
    if not data.get('gr_message_id'):
        await query.answer("Сессия истекла, начните заново.", show_alert=True)
        return
    mj = data.get('gr_message_json')
    mj = dict(mj) if isinstance(mj, dict) else {}
    markup = build_broadcast_markup(data.get('gr_buttons', []))
    if markup is not None:
        mj['reply_markup'] = markup.model_dump(exclude_none=True)
    else:
        mj.pop('reply_markup', None)

    edit_id = data.get('gr_edit_id')
    if edit_id:
        await db.update_greeting(edit_id, data['gr_from_chat_id'], data['gr_message_id'], mj)
        msg = "✅ Приветка обновлена!"
    else:
        await db.add_greeting(data['gr_from_chat_id'], data['gr_message_id'], mj)
        msg = "✅ Приветка добавлена!"
    await state.clear()
    await query.answer(msg)
    greetings = await db.get_all_greetings()
    await query.message.edit_text(
        "Список всех приветок:" if greetings else "Приветок пока нет.",
        reply_markup=get_admin_greetings_list_kb(greetings),
    )


@router.callback_query(F.data == "admin:subgram_mode", IsAdmin())
async def cq_subgram_mode(query: CallbackQuery):
    current = await db.get_setting('subgram_mode')
    if current not in ("both", "first_only", "second_only"):
        current = "both"
    await query.message.edit_text(
        "Выберите режим распределения ресурсов SubGram по этапам:",
        reply_markup=get_admin_subgram_mode_kb(current_mode=current)
    )

@router.callback_query(F.data.startswith("admin:set_subgram_mode:"), IsAdmin())
async def cq_set_subgram_mode(query: CallbackQuery):
    mode = query.data.split(":")[2]
    if mode not in ("both", "first_only", "second_only"):
        await query.answer("Недопустимый режим.", show_alert=True)
        return
    await db.set_setting('subgram_mode', mode)
    await query.answer("Режим SubGram обновлен.", show_alert=True)
    await cq_subgram_mode(query)


@router.callback_query(F.data == "admin:list_channels", IsAdmin())
async def cq_list_channels(query: CallbackQuery):
    channels = await db.get_all_admin_channels()
    text = "Список добавленных вручную каналов:" if channels else "Каналы еще не были добавлены."
    await query.message.edit_text(text, reply_markup=get_admin_channel_list_kb(channels))

@router.callback_query(F.data.startswith("admin:view_channel:"), IsAdmin())
async def cq_view_channel(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_channel_view_kb, _CHECK_TYPE_LABELS
    channel_id = int(query.data.split(":")[2])
    channels = await db.get_all_admin_channels()
    ch = next((c for c in channels if c['id'] == channel_id), None)
    if not ch:
        await query.answer("Канал не найден.", show_alert=True)
        return
    target_labels = {'all': '🌍 Всем', 'premium': '💎 Премиумам', 'non_premium': '👤 Не премиумам'}
    check_label = _CHECK_TYPE_LABELS.get(ch.get('check_type', 'none'), ch.get('check_type', 'none'))
    shown = ch.get('shown_count', 0)
    passed = ch.get('passed_count', 0)
    conv = f"{(passed / shown * 100):.0f}%" if shown else "—"
    text = (
        f"📺 <b>{ch['name']}</b>\n\n"
        f"🔗 Ссылка: {ch['url']}\n"
        f"👥 Аудитория: {target_labels.get(ch.get('premium_target', 'all'), '🌍 Всем')}\n"
        f"🔎 Проверка: {check_label}\n"
        f"🆔 ID канала: <code>{ch.get('chat_id') or '— (без проверки)'}</code>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👁 Показов: <b>{shown}</b>\n"
        f"✅ Прошли (подписались): <b>{passed}</b>\n"
        f"📈 Конверсия: <b>{conv}</b>"
    )
    await query.message.edit_text(text, reply_markup=get_admin_channel_view_kb(channel_id, ch.get('url')))
    await query.answer()


@router.callback_query(F.data.startswith("admin:delete_channel:"), IsAdmin())
async def cq_delete_channel(query: CallbackQuery):
    channel_id = int(query.data.split(":")[2])
    await db.delete_admin_channel(channel_id)
    await query.answer("Канал удален!", show_alert=True)
    await cq_list_channels(query)


@router.callback_query(F.data == "admin:cancel_fsm", IsAdmin())
async def cq_cancel_fsm(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq_admin_main_menu(query, state)

@router.callback_query(F.data == "admin:add_channel", IsAdmin())
async def cq_add_channel_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_channel_name)
    await query.message.edit_text(
        "<b>Шаг 1/4:</b> Введите название канала (текст на кнопке):",
        reply_markup=get_admin_cancel_kb()
    )
    await state.update_data(_wiz_msg=query.message.message_id)


@router.message(Admin.add_channel_name, F.text)
async def process_add_channel_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Admin.add_channel_url)
    await _wiz_edit(message, state, "<b>Шаг 2/4:</b> Теперь отправьте ссылку на канал (URL):",
                    reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_channel_url, F.text)
async def process_add_channel_url(message: Message, state: FSMContext):
    await state.update_data(url=message.text, op_stage=1)
    await state.set_state(Admin.add_channel_premium_target)
    await _wiz_edit(message, state, "<b>Шаг 3/4:</b> Кому показывать этот ресурс?",
                    reply_markup=get_admin_premium_target_kb())


@router.callback_query(Admin.add_channel_premium_target, F.data.startswith("admin_premium:"))
async def process_add_channel_premium_target(query: CallbackQuery, state: FSMContext):
    premium_target = query.data.split(":")[1]
    await state.update_data(premium_target=premium_target)
    await state.set_state(Admin.add_channel_check_type)
    await query.message.edit_text("<b>Шаг 4/4:</b> Выберите тип проверки подписки:",
                                  reply_markup=get_admin_check_type_kb())


@router.callback_query(Admin.add_channel_check_type, F.data.startswith("admin_check:"))
async def process_add_channel_check_type(query: CallbackQuery, state: FSMContext):
    check_type = query.data.split(":")[1]
    await state.update_data(check_type=check_type)

    if check_type in ['membership', 'join_request']:
        await state.set_state(Admin.add_channel_chat_id)
        await query.message.edit_text(
            "<b>Финальный шаг:</b> Для проверки подписки нужен ID канала.\n\n"
            "<b>Как получить ID:</b>\n"
            "1. Сделайте пост в вашем канале.\n"
            "2. Перешлите этот пост боту @userinfobot.\n"
            "3. Он покажет ID в строке `Forwarded from chat`.\n"
            "Отправьте этот ID (он начинается с -100...):",
            reply_markup=get_admin_cancel_kb()
        )
    else:
        data = await state.get_data()
        await db.add_admin_channel(
            name=data['name'], url=data['url'], op_stage=data['op_stage'],
            check_type=data['check_type'], premium_target=data['premium_target']
        )
        await state.clear()
        await query.answer("✅ Канал без проверки успешно добавлен!", show_alert=True)
        await cq_op_management(query)


@router.message(Admin.add_channel_chat_id, F.text)
async def process_add_channel_chat_id(message: Message, state: FSMContext):
    try:
        chat_id = int(message.text)
    except ValueError:
        await _wiz_edit(message, state,
                        "❌ ID канала должен быть числом.\n\n<b>Финальный шаг:</b> отправьте ID (начинается с -100...):",
                        reply_markup=get_admin_cancel_kb())
        return
    data = await state.get_data()
    await db.add_admin_channel(
        name=data['name'], url=data['url'], op_stage=data['op_stage'],
        check_type=data['check_type'], premium_target=data['premium_target'], chat_id=chat_id
    )
    await _wiz_edit(message, state,
                    "✅ <b>Канал добавлен!</b>\n\nМеню управления Обязательной Подпиской (ОП):",
                    reply_markup=get_admin_op_menu_kb())
    await state.clear()


def _spark(rows: list, key: str = 'total') -> str:
    """Простой текстовый бар-чарт по дням (премиум-эмодзи не нужны)."""
    if not rows:
        return "<i>нет данных</i>"
    blocks = "▁▂▃▄▅▆▇█"
    vals = [int(r[key]) for r in rows]
    mx = max(vals) or 1
    out = []
    for r, v in zip(rows, vals):
        idx = int((v / mx) * (len(blocks) - 1))
        day = r['day'].strftime('%d.%m') if hasattr(r['day'], 'strftime') else str(r['day'])
        out.append(f"{day}: {blocks[idx]} <b>{v}</b>")
    return "\n".join(out)


@router.callback_query(F.data == "admin:stats", IsAdmin())
async def cq_get_stats(query: CallbackQuery):
    await query.answer("Собираю статистику...")

    total_users = await db.get_users_count("total")
    users_today = await db.get_users_count("today")
    users_yesterday = await db.get_users_count("yesterday")
    users_week = await db.get_users_count("week")

    organic = await db.get_users_count_by_source('organic')
    organic_pct = (organic / total_users * 100) if total_users > 0 else 0

    op_total = await db.get_op_passed_count("total")
    op_today = await db.get_op_passed_count("today")
    op_week = await db.get_op_passed_count("week")

    circles = await db.get_circles_count()
    circle_views = await db.get_total_circle_views()
    open_reports = await db.count_open_reports()
    anon_active = await db.get_anon_active_count()
    anon_queue = await db.get_anon_queue_count()

    tasks_done = await db.get_total_tasks_completed()
    referrals = await db.get_total_referrals()
    reveals_done = await db.get_total_author_reveals()

    purchases = await db.get_purchase_stats()

    def _pk(kind):
        d = purchases.get(kind, {})
        return d.get('count', 0), d.get('stars', 0)
    v_cnt, v_st = _pk('views')
    a_cnt, a_st = _pk('authors')
    u_cnt, u_st = _pk('uploads')
    h_cnt, h_st = _pk('hide')

    stars_total = await db.get_stars_stats("total")
    stars_today = await db.get_stars_stats("today")
    stars_week = await db.get_stars_stats("week")

    users_chart = await db.get_users_by_day(14)
    stars_chart = await db.get_stars_by_day(14)

    stats_text = f"""📊 <b>Статистика Кружок-бота</b>

👥 <b>Пользователи:</b>
• Всего: <b>{total_users}</b>
• Сегодня: <b>{users_today}</b> · Вчера: <b>{users_yesterday}</b> · Неделя: <b>{users_week}</b>
🌱 Саморост: <b>{organic}</b> ({organic_pct:.1f}%)
🤝 Пришло по рефам: <b>{referrals}</b>

✅ <b>Прошли ОП:</b>
• Всего: <b>{op_total}</b> · Сегодня: <b>{op_today}</b> · Неделя: <b>{op_week}</b>

🎥 <b>Контент:</b>
• Кружков в ленте: <b>{circles}</b>
• Просмотров кружков всего: <b>{circle_views}</b>
• Раскрытий авторов сделано: <b>{reveals_done}</b>
• Заданий выполнено: <b>{tasks_done}</b>
• Открытых жалоб: <b>{open_reports}</b>

🛒 <b>Покупки за ⭐ (кол-во / звёзд):</b>
• Просмотры кружков: <b>{v_cnt}</b> / {v_st}⭐
• Раскрытие авторов: <b>{a_cnt}</b> / {a_st}⭐
• Скрытие авторства: <b>{h_cnt}</b> / {h_st}⭐
• Доп-загрузки: <b>{u_cnt}</b> / {u_st}⭐

💬 <b>Анон-чат:</b>
• Активных диалогов: <b>{anon_active}</b>
• В очереди поиска: <b>{anon_queue}</b>

⭐️ <b>Звёзды всего:</b> <b>{stars_total}</b> · Сегодня: {stars_today} · Неделя: {stars_week}

📈 <b>Новые юзеры (14 дней):</b>
{_spark(users_chart)}

⭐️ <b>Звёзды по дням (14 дней):</b>
{_spark(stars_chart)}
"""
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    from aiogram.types import InlineKeyboardButton as _IKBtn
    kb = _IKB()
    kb.row(_IKBtn(text="⬅️ Назад", callback_data="admin:main_menu"))
    try:
        await query.message.edit_text(stats_text, reply_markup=kb.as_markup())
    except Exception:
        await query.message.answer(stats_text, reply_markup=kb.as_markup())




@router.callback_query(F.data == "admin:export_users", IsAdmin())
async def cq_export_users(query: CallbackQuery):
    await query.answer("Начинаю выгрузку ID...")
    user_ids = await db.get_all_user_ids()

    if not user_ids:
        await query.answer("В базе данных еще нет пользователей.", show_alert=True)
        return

    file_content = "\n".join(map(str, user_ids))
    file_data = io.BytesIO(file_content.encode('utf-8'))
    input_file = BufferedInputFile(file_data.read(), filename="user_ids.txt")

    await query.message.answer_document(input_file, caption=f"✅ Выгружено {len(user_ids)} пользователей.")


@router.callback_query(F.data == "admin:ad_links", IsAdmin())
async def cq_ad_links_menu(query: CallbackQuery, state: FSMContext):
    await state.clear()
    page, per_page = 1, 10
    links, total = await db.get_ad_links_paginated(page=page, per_page=per_page)
    text = "🔗 **Управление рекламными ссылками**\n\nВыберите ссылку для просмотра статистики или создайте новую:"
    await query.message.edit_text(text, reply_markup=await get_ad_links_list_kb(links, page=page, per_page=per_page, total=total))

@router.callback_query(F.data.startswith("admin:ad_links_page:"), IsAdmin())
async def cq_ad_links_page(query: CallbackQuery):
    try:
        _, _, page_str, per_page_str = query.data.split(":", 3)
        page = int(page_str)
        per_page = int(per_page_str)
    except Exception:
        page, per_page = 1, 10

    links, total = await db.get_ad_links_paginated(page=page, per_page=per_page)
    text = "🔗 **Управление рекламными ссылками**\n\nВыберите ссылку для просмотра статистики или создайте новую:"
    try:
        await query.message.edit_reply_markup(reply_markup=await get_ad_links_list_kb(links, page=page, per_page=per_page, total=total))
    except Exception:
        await query.message.edit_text(text, reply_markup=await get_ad_links_list_kb(links, page=page, per_page=per_page, total=total))


@router.callback_query(F.data.startswith("admin:ad_stats:"), IsAdmin())
async def cq_ad_link_stats(query: CallbackQuery, bot: Bot):
    link_id = int(query.data.split(":")[2])
    link_name = query.data.split(":")[3]

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=adv_{link_name}"

    stats = await db.get_ad_link_stats(link_id)

    total = stats['total_clicks']
    unique = stats['unique_users']
    premium = stats['premium_clicks']
    unique_premium = stats['unique_premium_users']
    op_passed = stats['completed_op_users']

    conv_unique = f"{(unique / total * 100):.2f}%" if total > 0 else "0.00%"
    conv_premium = f"{(premium / total * 100):.2f}%" if total > 0 else "0.00%"
    conv_unique_premium = f"{(unique_premium / unique * 100):.2f}%" if unique > 0 else "0.00%"

    conv_op_unique = f"{(op_passed / unique * 100):.2f}%" if unique > 0 else "0.00%"

    text = f"""📈 <b>Статистика по ссылке: {link_name}</b>

🔗 <code>{ref_link}</code>

<b>Переходы:</b>
🔗 Всего: <b>{total}</b>
👤 Уникальных: <b>{unique}</b> ({conv_unique})
💎 Премиум: <b>{premium}</b> ({conv_premium})
👑 Уник. премиум: <b>{unique_premium}</b> ({conv_unique_premium})

<b>Прошли ОП:</b>
✅ <b>{op_passed}</b> из {unique} уник. ({conv_op_unique})
"""
    await query.message.edit_text(text, reply_markup=get_ad_link_stats_kb(link_id))


@router.callback_query(F.data == "admin:add_ad_link", IsAdmin())
async def cq_add_ad_link_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_ad_link_name)
    await query.message.edit_text(
        "Введите уникальное название для новой ссылки (например, <code>telegram_ads_1</code> или <code>post_promo</code>). "
        "Используйте латиницу, цифры, <code>_</code> и <code>-</code>.",
        reply_markup=get_admin_cancel_kb()
    )
    await state.update_data(_wiz_msg=query.message.message_id)


@router.message(Admin.add_ad_link_name, F.text)
async def process_add_ad_link(message: Message, state: FSMContext):
    link_name = message.text.strip()

    if not link_name or not link_name.isascii() or not all(c.isalnum() or c in "_-" for c in link_name):
        await _wiz_edit(message, state,
                        "❌ Только латиница, цифры, <code>_</code> и <code>-</code> (без пробелов и кириллицы).\n"
                        "Например: <code>telegram_ads_1</code>. Попробуйте снова:",
                        reply_markup=get_admin_cancel_kb())
        return

    new_link = await db.add_ad_link(name=link_name)
    if not new_link:
        await _wiz_edit(message, state,
                        f"❌ Ссылка <code>{link_name}</code> уже существует. Введите другое название:",
                        reply_markup=get_admin_cancel_kb())
        return

    links = await db.get_all_ad_links()
    await _wiz_edit(message, state, f"✅ Ссылка <code>{link_name}</code> создана!\n\n🔗 Управление рекламными ссылками:",
                    reply_markup=await get_ad_links_list_kb(links))
    await state.clear()


@router.callback_query(F.data.startswith("admin:del_ad_link_ask:"), IsAdmin())
async def cq_del_ad_link_ask(query: CallbackQuery):
    from keyboards.inline_keyboards import get_ad_link_delete_confirm_kb
    link_id = int(query.data.split(":")[2])
    await query.message.edit_text(
        "⚠️ <b>Удалить рекламную ссылку?</b>\n\n"
        "Вместе с ней удалится <b>вся её статистика</b> — это нельзя отменить.",
        reply_markup=get_ad_link_delete_confirm_kb(link_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("admin:delete_ad_link:"), IsAdmin())
async def cq_delete_ad_link(query: CallbackQuery, state: FSMContext):
    link_id = int(query.data.split(":")[2])
    await db.delete_ad_link(link_id)
    await query.answer("Ссылка и вся её статистика удалены!", show_alert=True)
    await cq_ad_links_menu(query, state=state)

@router.callback_query(F.data == "admin:tasks_menu", IsAdmin())
async def cq_tasks_menu(query: CallbackQuery):
    await query.message.edit_text(
        "Меню управления заданиями:",
        reply_markup=get_admin_tasks_menu_kb()
    )

@router.callback_query(F.data == "admin:list_tasks", IsAdmin())
async def cq_list_tasks(query: CallbackQuery):
    tasks = await db.get_all_admin_tasks()
    text = "Список созданных заданий:" if tasks else "Задания еще не были добавлены."
    await query.message.edit_text(text, reply_markup=get_admin_tasks_list_kb(tasks))

@router.callback_query(F.data.startswith("admin:view_task:"), IsAdmin())
async def cq_view_task(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_task_view_kb, _CHECK_TYPE_LABELS
    task_id = int(query.data.split(":")[2])
    task = await db.get_admin_task_by_id(task_id)
    if not task:
        await query.answer("Задание не найдено.", show_alert=True)
        return
    check_label = _CHECK_TYPE_LABELS.get(task.get('check_type', 'none'), task.get('check_type', 'none'))
    text = (
        f"✍️ <b>{task['name']}</b>\n\n"
        f"🔗 Ссылка: {task.get('url') or '—'}\n"
        f"🎁 Награда: <b>+{task.get('reward_attempts', 0)}</b> попыток\n"
        f"🔎 Проверка: {check_label}\n"
        f"🆔 ID канала: <code>{task.get('chat_id') or '— (без проверки)'}</code>"
    )
    await query.message.edit_text(text, reply_markup=get_admin_task_view_kb(task_id, task.get('url') or ''))
    await query.answer()


@router.callback_query(F.data.startswith("admin:delete_task:"), IsAdmin())
async def cq_delete_task(query: CallbackQuery):
    task_id = int(query.data.split(":")[2])
    await db.delete_admin_task(task_id)
    await query.answer("Задание удалено!", show_alert=True)
    await cq_list_tasks(query)

@router.callback_query(F.data == "admin:add_task", IsAdmin())
async def cq_add_task_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_task_name)
    await query.message.edit_text(
        "<b>Шаг 1/5:</b> Введите название задания (текст на кнопке):",
        reply_markup=get_admin_cancel_kb()
    )
    await state.update_data(_wiz_msg=query.message.message_id)

@router.message(Admin.add_task_name, F.text)
async def process_add_task_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Admin.add_task_reward)
    await _wiz_edit(message, state, "<b>Шаг 2/5:</b> Введите награду за выполнение (целое число, например, 3):",
                    reply_markup=get_admin_cancel_kb())

@router.message(Admin.add_task_reward, F.text)
async def process_add_task_reward(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await _wiz_edit(message, state, "❌ Нужно целое положительное число.\n\n<b>Шаг 2/5:</b> Введите награду:",
                        reply_markup=get_admin_cancel_kb())
        return
    await state.update_data(reward_attempts=int(message.text))
    await state.set_state(Admin.add_task_url)
    await _wiz_edit(message, state, "<b>Шаг 3/5:</b> Теперь отправьте ссылку на канал (URL):",
                    reply_markup=get_admin_cancel_kb())

@router.message(Admin.add_task_url, F.text)
async def process_add_task_url(message: Message, state: FSMContext):
    await state.update_data(url=message.text)
    await state.set_state(Admin.add_task_check_type)
    await _wiz_edit(message, state, "<b>Шаг 4/5:</b> Выберите тип проверки подписки:",
                    reply_markup=get_admin_check_type_kb())

@router.callback_query(Admin.add_task_check_type, F.data.startswith("admin_check:"))
async def process_add_task_check_type(query: CallbackQuery, state: FSMContext):
    check_type = query.data.split(":")[1]
    await state.update_data(check_type=check_type)

    if check_type in ['membership', 'join_request']:
        await state.set_state(Admin.add_task_chat_id)
        await query.message.edit_text("<b>Шаг 5/5:</b> Отправьте ID канала (начинается с -100...):")
    else:
        data = await state.get_data()
        await db.add_admin_task(
            name=data['name'], url=data['url'],
            reward_attempts=data['reward_attempts'], check_type=data['check_type']
        )
        await state.clear()
        await query.answer("✅ Задание без проверки успешно добавлено!", show_alert=True)
        await cq_tasks_menu(query)

@router.message(Admin.add_task_chat_id, F.text)
async def process_add_task_chat_id(message: Message, state: FSMContext):
    try:
        chat_id = int(message.text)
    except ValueError:
        await _wiz_edit(message, state, "❌ ID канала должен быть числом.\n\n<b>Шаг 5/5:</b> Отправьте ID (начинается с -100...):",
                        reply_markup=get_admin_cancel_kb())
        return
    data = await state.get_data()
    await db.add_admin_task(
        name=data['name'], url=data['url'],
        reward_attempts=data['reward_attempts'],
        check_type=data['check_type'], chat_id=chat_id
    )
    await _wiz_edit(message, state, "✅ <b>Задание добавлено!</b>\n\nМеню управления заданиями:",
                    reply_markup=get_admin_tasks_menu_kb())
    await state.clear()



@router.callback_query(F.data == "admin:shows_menu", IsAdmin())
async def cq_shows_menu(query: CallbackQuery):
    await query.message.edit_text(
        "📺 **Управление показами**\n\n"
        "Показы — это сообщения, которые автоматически отправляются пользователям через определенное время после команды /start.\n"
        "Вы можете настроить задержку и целевую аудиторию для каждого показа.",
        reply_markup=get_admin_shows_menu_kb()
    )


@router.callback_query(F.data == "admin:add_show", IsAdmin())
async def cq_add_show_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_show_message)
    await query.message.edit_text(
        "Перешлите сюда сообщение, которое хотите использовать в качестве показа.\n\n"
        "Можно пересылать из каналов, от других ботов или пользователей.\n"
        "Поддерживаются фото, гифки, видео, стикеры и текст с кнопками.",
        reply_markup=get_admin_cancel_kb()
    )


@router.message(Admin.add_show_message, ~F.text.startswith("/"))
async def process_add_show_message(message: Message, state: FSMContext):
    try:
        from_chat_id = message.forward_from_chat.id if message.forward_from_chat else message.chat.id
        message_id = message.forward_from_message_id if message.forward_from_message_id else message.message_id
        
        import json
        import datetime as _dt
        from enum import Enum as _Enum

        raw_dump = message.model_dump(exclude_none=True)

        def to_jsonable(obj):
            if hasattr(obj, '__class__') and 'Default' in obj.__class__.__name__:
                return None
            if isinstance(obj, _dt.datetime):
                return obj.isoformat()
            if isinstance(obj, _Enum):
                return obj.value
            if isinstance(obj, dict):
                result = {}
                for k, v in obj.items():
                    val = to_jsonable(v)
                    if val is not None:
                        result[k] = val
                return result
            if isinstance(obj, (list, tuple, set)):
                return [to_jsonable(v) for v in obj]
            try:
                json.dumps(obj)
                return obj
            except Exception:
                return str(obj)

        message_json = to_jsonable(raw_dump)
        
        await state.update_data(
            from_chat_id=from_chat_id,
            message_id=message_id,
            message_json=message_json
        )
        
        await state.set_state(Admin.add_show_delay)
        await message.answer(
            "<b>Шаг 2/3:</b> Через сколько минут после /start отправлять этот показ?\n\n"
            "Примеры:\n"
            "• <code>5</code> — через 5 минут\n"
            "• <code>60</code> — через 1 час\n"
            "• <code>120</code> — через 2 часа"
        )

    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при добавлении показа: {e}", parse_mode=None)


@router.message(Admin.add_show_delay, F.text)
async def process_add_show_delay(message: Message, state: FSMContext):
    try:
        delay_minutes = int(message.text.strip())
        if delay_minutes < 1:
            await message.answer("❌ Задержка должна быть минимум 1 минута.")
            return
        
        await state.update_data(delay_minutes=delay_minutes)
        await state.set_state(Admin.add_show_target)
        await message.answer(
            "<b>Шаг 3/3:</b> Выберите целевую аудиторию для показа:",
            reply_markup=get_admin_show_target_kb()
        )
    
    except ValueError:
        await message.answer("❌ Ошибка. Введите целое число (количество минут).")


@router.callback_query(Admin.add_show_target, F.data.startswith("admin_show_target:"))
async def process_add_show_target(query: CallbackQuery, state: FSMContext):
    target_audience = query.data.split(":")[1]
    data = await state.get_data()
    
    await db.add_scheduled_show(
        from_chat_id=data['from_chat_id'],
        message_id=data['message_id'],
        delay_minutes=data['delay_minutes'],
        target_audience=target_audience,
        message_json=data['message_json']
    )
    
    await state.clear()
    
    target_labels = {
        'all': '🌍 Всем пользователям',
        'passed_op': '✅ Прошедшим ОП',
        'not_passed_op': '❌ Не прошедшим ОП'
    }
    
    target_text = target_labels.get(target_audience, 'всем')
    delay_minutes = data['delay_minutes']
    
    await query.answer("✅ Показ успешно добавлен!", show_alert=True)
    await query.message.edit_text(
        f"✅ Показ успешно добавлен!\n\n"
        f"⏱ Задержка: {delay_minutes} минут\n"
        f"👥 Аудитория: {target_text}",
        reply_markup=get_admin_shows_menu_kb()
    )


@router.callback_query(F.data == "admin:list_shows", IsAdmin())
async def cq_list_shows(query: CallbackQuery):
    shows = await db.get_all_scheduled_shows()
    text = "📋 Список всех показов:" if shows else "Показов пока нет."
    await query.message.edit_text(text, reply_markup=get_admin_shows_list_kb(shows))


@router.callback_query(F.data.startswith("admin:delete_show:"), IsAdmin())
async def cq_delete_show(query: CallbackQuery):
    show_id = int(query.data.split(":")[2])
    await db.delete_scheduled_show(show_id)
    await query.answer("Показ удален!", show_alert=True)
    await cq_list_shows(query)


@router.callback_query(F.data.startswith("admin:preview_show:"), IsAdmin())
async def cq_preview_show(query: CallbackQuery, bot: Bot):
    show_id = int(query.data.split(":")[2])
    shows = await db.get_all_scheduled_shows()
    show = next((s for s in shows if s['id'] == show_id), None)

    if not show:
        await query.answer("Показ не найден.", show_alert=True)
        return

    sent = await send_stored_message(
        bot=bot,
        chat_id=query.from_user.id,
        from_chat_id=show['from_chat_id'],
        message_id=show['message_id'],
        msg_json_raw=show.get('message_json'),
        label=f"preview_show#{show_id}",
    )
    if sent:
        await query.answer()
    else:
        await query.answer("Не удалось показать показ.", show_alert=True)



@router.callback_query(F.data == "admin:special_button_menu", IsAdmin())
async def cq_special_button_menu(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_special_button_menu_kb
    await query.message.edit_text(
        "🔗 <b>Рекламные кнопки</b>\n\n"
        "Кнопки-ссылки, которые показываются пользователям прямо в боте: "
        "под кружком в ленте, в профиле, на экране приглашения друга и на экранах покупок.\n\n"
        "Активных кнопок может быть <b>несколько</b> — на каждом экране показывается "
        "<b>случайная</b> из подходящих.",
        reply_markup=get_admin_special_button_menu_kb()
    )


@router.callback_query(F.data == "admin:add_special_button", IsAdmin())
async def cq_add_special_button_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_special_button_text)
    await query.message.edit_text(
        "Отправьте текст рекламной кнопки.\n\n"
        "💡 Хотите премиум-эмодзи иконку? Вставьте любой премиум-эмодзи <b>в начало</b> текста — "
        "бот автоматически распознает его ID и использует как иконку. Сам символ из текста уберётся.\n\n"
        "Пример: <code>💫 Забрать подарок</code>",
        reply_markup=get_admin_cancel_kb()
    )
    await state.update_data(_wiz_msg=query.message.message_id)


@router.message(Admin.add_special_button_text, F.text)
async def process_add_special_button_text(message: Message, state: FSMContext):
    clean_text, emoji_id = extract_icon_from_message(message)
    await state.update_data(special_text=clean_text, special_icon_emoji_id=emoji_id)
    await state.set_state(Admin.add_special_button_url)
    icon_note = f"✅ Иконка распознана: <code>{emoji_id}</code>\n" if emoji_id else ""
    await _wiz_edit(message, state,
                    f"{icon_note}Теперь отправьте ссылку (URL) для кнопки:",
                    reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_special_button_url, F.text)
async def process_add_special_button_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        await _wiz_edit(message, state,
                        "❌ Ссылка должна начинаться с http:// или https://. Отправьте ссылку снова:",
                        reply_markup=get_admin_cancel_kb())
        return
    await state.update_data(special_url=url)
    await state.set_state(Admin.add_special_button_color)
    from keyboards.inline_keyboards import get_admin_special_button_color_kb
    await _wiz_edit(message, state, "Выберите цвет кнопки:",
                    reply_markup=get_admin_special_button_color_kb())


@router.callback_query(Admin.add_special_button_color, F.data.startswith("admin:sbcolor:"), IsAdmin())
async def process_add_special_button_color(query: CallbackQuery, state: FSMContext):
    color = query.data.split(":")[-1]
    if color not in ("primary", "success", "danger", "secondary"):
        await query.answer("Неизвестный цвет.", show_alert=True)
        return
    await state.update_data(
        special_button_style=color,
        sb_show_feed=True, sb_show_profile=True,
        sb_show_referral=False, sb_show_purchase=False,
    )
    await state.set_state(Admin.add_special_button_positions)
    from keyboards.inline_keyboards import get_admin_special_button_positions_kb
    data = await state.get_data()
    kb = get_admin_special_button_positions_kb(
        show_in_feed=data.get("sb_show_feed", True),
        show_in_profile=data.get("sb_show_profile", True),
        show_in_referral=data.get("sb_show_referral", False),
        show_in_purchase=data.get("sb_show_purchase", False),
    )
    color_labels = {"primary": "🔵 Синий", "success": "🟢 Зелёный",
                    "danger": "🔴 Красный", "secondary": "⚫ Серый"}
    await query.message.edit_text(
        f"Цвет: <b>{color_labels.get(color, color)}</b>\n\n"
        "Где показывать кнопку? Отметьте нужные экраны (✅) и нажмите «Сохранить».",
        reply_markup=kb
    )
    await query.answer()


@router.callback_query(F.data.startswith("admin:sbpos:"), IsAdmin())
async def cq_special_button_positions(query: CallbackQuery, state: FSMContext):
    action = query.data.split(":")[-1]
    data = await state.get_data()
    if action in ("feed", "profile", "referral", "purchase"):
        key = f"sb_show_{action}"
        default_on = action in ("feed", "profile")
        current = bool(data.get(key, default_on))
        await state.update_data(**{key: not current})
        from keyboards.inline_keyboards import get_admin_special_button_positions_kb
        updated = await state.get_data()
        await query.message.edit_reply_markup(
            reply_markup=get_admin_special_button_positions_kb(
                show_in_feed=updated.get("sb_show_feed", True),
                show_in_profile=updated.get("sb_show_profile", True),
                show_in_referral=updated.get("sb_show_referral", False),
                show_in_purchase=updated.get("sb_show_purchase", False),
            )
        )
        await query.answer()
        return
    if action == "save":
        special_text = data.get("special_text")
        special_url = data.get("special_url")
        show_in_feed = bool(data.get("sb_show_feed", True))
        show_in_profile = bool(data.get("sb_show_profile", True))
        show_in_referral = bool(data.get("sb_show_referral", False))
        show_in_purchase = bool(data.get("sb_show_purchase", False))
        special_icon_emoji_id = data.get("special_icon_emoji_id")
        button_style = data.get("special_button_style", "primary")
        if not special_text or not special_url:
            await query.answer("Не хватает данных для сохранения.", show_alert=True)
            return
        if not (show_in_feed or show_in_profile or show_in_referral or show_in_purchase):
            await query.answer("Выберите хотя бы один экран для показа.", show_alert=True)
            return
        await db.add_special_ad_button(
            text=special_text,
            url=special_url,
            show_in_feed=show_in_feed,
            show_in_profile=show_in_profile,
            show_in_referral=show_in_referral,
            show_in_purchase=show_in_purchase,
            icon_emoji_id=special_icon_emoji_id,
            button_style=button_style,
        )
        await state.clear()
        await query.answer("✅ Кнопка добавлена и сразу активна!", show_alert=False)
        from keyboards.inline_keyboards import get_admin_special_button_menu_kb
        await query.message.edit_text(
            "🔗 <b>Рекламная кнопка добавлена.</b>\n\n"
            "Она активна. Если активных кнопок несколько — на каждом экране "
            "показывается случайная из них. Управлять можно в списке кнопок.",
            reply_markup=get_admin_special_button_menu_kb()
        )
        return
    await query.answer()


@router.callback_query(F.data == "admin:list_special_buttons", IsAdmin())
async def cq_list_special_buttons(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_special_buttons_list_kb
    buttons = await db.get_all_special_ad_buttons()
    await query.message.edit_text(
        f"📋 <b>Список рекламных кнопок ({len(buttons)})</b>\n\n"
        "✅ — активна (показывается в боте), ❌ — выключена. Нажмите на кнопку, чтобы вкл/выкл. "
        "Активных может быть несколько — на каждом экране показывается случайная.",
        reply_markup=get_admin_special_buttons_list_kb(buttons)
    )


@router.callback_query(F.data.startswith("admin:toggle_special_button:"), IsAdmin())
async def cq_toggle_special_button(query: CallbackQuery):
    button_id = int(query.data.split(':')[-1])
    buttons = await db.get_all_special_ad_buttons()

    current_button = next((b for b in buttons if b['id'] == button_id), None)
    if current_button:
        new_status = not current_button.get('is_active', False)
        await db.toggle_special_ad_button(button_id, new_status)

    from keyboards.inline_keyboards import get_admin_special_buttons_list_kb
    buttons = await db.get_all_special_ad_buttons()
    await query.message.edit_reply_markup(reply_markup=get_admin_special_buttons_list_kb(buttons))
    await query.answer("Статус обновлён!")


@router.callback_query(F.data.startswith("admin:delete_special_button:"), IsAdmin())
async def cq_delete_special_button(query: CallbackQuery):
    button_id = int(query.data.split(':')[-1])
    await db.delete_special_ad_button(button_id)

    from keyboards.inline_keyboards import get_admin_special_buttons_list_kb
    buttons = await db.get_all_special_ad_buttons()
    await query.message.edit_text(
        f"📋 <b>Список рекламных кнопок ({len(buttons)})</b>",
        reply_markup=get_admin_special_buttons_list_kb(buttons)
    )
    await query.answer("Кнопка удалена!")


@router.callback_query(F.data == "admin:shows_d_menu", IsAdmin())
async def cq_shows_d_menu(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_shows_d_menu_kb
    await query.message.edit_text(
        "⚡️ <b>Реклама в ленте</b>\n\n"
        "Показывается пользователю прямо в ленте, между кружками во время просмотра. "
        "Чтобы не спамить, одному человеку приходит не чаще раза в 5–10 минут. "
        "Если реклам несколько — выбирается случайная.",
        reply_markup=get_admin_shows_d_menu_kb()
    )


@router.callback_query(F.data == "admin:add_show_d", IsAdmin())
async def cq_add_show_d_start(query: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.add_greeting_message)
    await state.update_data(adding_show_d=True)
    await query.message.edit_text(
        "Перешлите сообщение, которое будет показываться в ленте между кружками "
        "(можно с фото / видео / кнопками):",
        reply_markup=get_admin_cancel_kb()
    )


@router.callback_query(F.data == "admin:list_shows_d", IsAdmin())
async def cq_list_shows_d(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_shows_d_list_kb
    shows = await db.get_all_shows_d()
    await query.message.edit_text(
        f"⚡️ <b>Реклама в ленте — список ({len(shows)})</b>\n\n"
        "Нажмите на запись, чтобы посмотреть превью.",
        reply_markup=get_admin_shows_d_list_kb(shows)
    )


@router.callback_query(F.data.startswith("admin:delete_show_d:"), IsAdmin())
async def cq_delete_show_d(query: CallbackQuery):
    show_id = int(query.data.split(':')[-1])
    await db.delete_show_d(show_id)

    from keyboards.inline_keyboards import get_admin_shows_d_list_kb
    shows = await db.get_all_shows_d()
    await query.message.edit_text(
        f"⚡️ <b>Реклама в ленте — список ({len(shows)})</b>",
        reply_markup=get_admin_shows_d_list_kb(shows)
    )
    await query.answer("Реклама удалена!")


@router.callback_query(F.data.startswith("admin:preview_show_d:"), IsAdmin())
async def cq_preview_show_d(query: CallbackQuery, bot: Bot):
    show_id = int(query.data.split(':')[-1])
    show = await db.get_show_d_by_id(show_id)
    if not show:
        await query.answer("Реклама не найдена.", show_alert=True)
        return

    sent = await send_stored_message(
        bot=bot,
        chat_id=query.from_user.id,
        from_chat_id=show['from_chat_id'],
        message_id=show['message_id'],
        msg_json_raw=show.get('message_json'),
        label=f"preview_show_d#{show_id}",
    )
    if sent:
        await query.answer()
    else:
        await query.answer("Не удалось показать превью.", show_alert=True)


@router.callback_query(F.data == "admin:shows_n_menu", IsAdmin())
async def cq_shows_n_menu(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_shows_n_menu_kb
    await query.message.edit_text(
        "📺 <b>Реклама по таймеру</b>\n\n"
        "Приходит пользователю автоматически через заданное время после первого запуска бота "
        "(например, через 60 минут). У каждой рекламы своя задержка.",
        reply_markup=get_admin_shows_n_menu_kb()
    )


@router.callback_query(F.data == "admin:add_show_n", IsAdmin())
async def cq_add_show_n_start(query: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.add_show_n_delay)
    await query.message.edit_text(
        "Через сколько минут после запуска бота отправить эту рекламу?\n"
        "Введите число минут (например: 15, 45, 120):",
        reply_markup=get_admin_cancel_kb()
    )


@router.message(Admin.add_show_n_delay, F.text, IsAdmin())
async def cq_add_show_n_delay_text(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        delay_minutes = int(text)
        if delay_minutes <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите корректное число минут (целое положительное число).\n"
            "Например: 10, 30, 60, 120",
            reply_markup=get_admin_cancel_kb()
        )
        return

    await state.update_data(show_n_delay=delay_minutes, adding_show_n=True)
    await state.set_state(Admin.add_greeting_message)

    await message.answer(
        f"Перешлите сообщение для рекламы (придёт через {delay_minutes} мин после запуска бота). "
        "Можно с фото / видео / кнопками:",
        reply_markup=get_admin_cancel_kb()
    )


@router.callback_query(F.data == "admin:list_shows_n", IsAdmin())
async def cq_list_shows_n(query: CallbackQuery):
    from keyboards.inline_keyboards import get_admin_shows_n_list_kb
    shows = await db.get_all_shows_n()
    await query.message.edit_text(
        f"📺 <b>Реклама по таймеру — список ({len(shows)})</b>\n\n"
        "Нажмите на запись, чтобы посмотреть превью.",
        reply_markup=get_admin_shows_n_list_kb(shows)
    )


@router.callback_query(F.data.startswith("admin:delete_show_n:"), IsAdmin())
async def cq_delete_show_n(query: CallbackQuery):
    show_id = int(query.data.split(':')[-1])
    await db.delete_show_n(show_id)

    from keyboards.inline_keyboards import get_admin_shows_n_list_kb
    shows = await db.get_all_shows_n()
    await query.message.edit_text(
        f"📺 <b>Реклама по таймеру — список ({len(shows)})</b>",
        reply_markup=get_admin_shows_n_list_kb(shows)
    )
    await query.answer("Реклама удалена!")


@router.callback_query(F.data.startswith("admin:preview_show_n:"), IsAdmin())
async def cq_preview_show_n(query: CallbackQuery, bot: Bot):
    show_id = int(query.data.split(':')[-1])
    show = await db.get_show_n_by_id(show_id)
    if not show:
        await query.answer("Реклама не найдена.", show_alert=True)
        return

    sent = await send_stored_message(
        bot=bot,
        chat_id=query.from_user.id,
        from_chat_id=show['from_chat_id'],
        message_id=show['message_id'],
        msg_json_raw=show.get('message_json'),
        label=f"preview_show_n#{show_id}",
    )
    if sent:
        await query.answer()
    else:
        await query.answer("Не удалось показать превью.", show_alert=True)

@router.callback_query(F.data == "admin:stats", IsAdmin())
async def cq_stats(query: CallbackQuery):
    users_total = await db.get_users_count("total")
    users_today = await db.get_users_count("today")
    users_yesterday = await db.get_users_count("yesterday")
    users_week = await db.get_users_count("week")
    
    organic_total = await db.get_users_count_by_source("organic")
    
    op1_total = await db.get_first_op_passed_count("total")
    op1_today = await db.get_first_op_passed_count("today")
    op1_yesterday = await db.get_first_op_passed_count("yesterday")
    op1_week = await db.get_first_op_passed_count("week")
    
    op2_total = await db.get_op_passed_count("total")
    op2_today = await db.get_op_passed_count("today")
    op2_yesterday = await db.get_op_passed_count("yesterday")
    op2_week = await db.get_op_passed_count("week")
    
    tasks_completed = await db.get_total_tasks_completed()
    examples_solved = await db.get_total_examples_solved()
    
    text = f"""
📊 <b>Статистика бота</b>

👥 <b>Пользователи:</b>
• Всего: <b>{users_total}</b>
• За сегодня: <b>{users_today}</b>
• За вчера: <b>{users_yesterday}</b>
• За неделю: <b>{users_week}</b>

🌱 <b>Саморост:</b>
• Всего: <b>{organic_total}</b> ({organic_total/users_total*100:.1f}% от всех)

✅ <b>Прошли ОП1:</b>
• Всего: <b>{op1_total}</b>
• Сегодня: <b>{op1_today}</b>
• Вчера: <b>{op1_yesterday}</b>
• За неделю: <b>{op1_week}</b>

✅ <b>Прошли ОП2:</b>
• Всего: <b>{op2_total}</b>
• Сегодня: <b>{op2_today}</b>
• Вчера: <b>{op2_yesterday}</b>
• За неделю: <b>{op2_week}</b>

📋 <b>Дополнительно:</b>
• Выполнено заданий: <b>{tasks_completed}</b>
• Решено примеров: <b>{examples_solved}</b>
"""
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    
    await query.message.edit_text(text, reply_markup=builder.as_markup())



_SERVICE_FIELD_LABELS = {
    'op1_enabled':    'ОП Этап-1 (вкл/выкл)',
    'op1_max':        'Макс. ресурсов ОП-1',
    'op1_priority':   'Приоритет ОП-1',
    'op2_enabled':    'ОП Этап-2 (вкл/выкл)',
    'op2_max':        'Макс. ресурсов ОП-2',
    'op2_priority':   'Приоритет ОП-2',
    'tasks_enabled':  'Задания (вкл/выкл)',
    'tasks_max':      'Макс. заданий',
    'tasks_priority': 'Приоритет заданий',
    'api_key':        'API ключ',
}

_SERVICE_NAMES = {
    'admin':   'Admin (свои каналы)',
    'subgram': 'SubGram',
    'botohub': 'BotoHub',
}


@router.callback_query(F.data == "admin:services", IsAdmin())
async def cq_admin_services(query: CallbackQuery, state: FSMContext):
    await state.clear()
    cfgs = await db.get_all_service_settings()
    s1 = await db.get_op_stage_limit(1)
    s2 = await db.get_op_stage_limit(2)
    text = (
        "⚙️ <b>Настройка источников ресурсов</b>\n\n"
        "Выберите сервис для настройки или измените глобальные лимиты этапов ОП.\n"
        "Приоритет — чем меньше число, тем раньше берутся ресурсы из этого сервиса."
    )
    try:
        await query.message.edit_text(text, reply_markup=get_admin_services_menu_kb(cfgs, s1, s2))
    except Exception:
        await query.message.answer(text, reply_markup=get_admin_services_menu_kb(cfgs, s1, s2))


@router.callback_query(F.data.startswith("admin:svc_edit:"), IsAdmin())
async def cq_svc_edit(query: CallbackQuery, state: FSMContext):
    await state.clear()
    svc = query.data.split(":")[2]
    cfg = await db.get_service_settings(svc)
    if not cfg:
        await query.answer("Сервис не найден.", show_alert=True)
        return
    name = _SERVICE_NAMES.get(svc, svc)
    text = f"⚙️ <b>Настройки сервиса: {name}</b>"
    try:
        await query.message.edit_text(text, reply_markup=get_admin_service_edit_kb(cfg))
    except Exception:
        await query.message.answer(text, reply_markup=get_admin_service_edit_kb(cfg))


@router.callback_query(F.data.startswith("admin:svc_tog:"), IsAdmin())
async def cq_svc_toggle(query: CallbackQuery, state: FSMContext):
    """Переключение булевой настройки сервиса."""
    parts = query.data.split(":")
    svc   = parts[2]
    field = parts[3]
    cfg = await db.get_service_settings(svc)
    if not cfg:
        await query.answer("Сервис не найден.", show_alert=True)
        return
    new_val = not bool(cfg.get(field, True))
    await db.update_service_field(svc, field, new_val)
    cfg[field] = new_val
    label = _SERVICE_FIELD_LABELS.get(field, field)
    state_str = "✅ включено" if new_val else "❌ выключено"
    await query.answer(f"{label}: {state_str}")
    name = _SERVICE_NAMES.get(svc, svc)
    try:
        await query.message.edit_text(
            f"⚙️ <b>Настройки сервиса: {name}</b>",
            reply_markup=get_admin_service_edit_kb(cfg),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin:svc_num:"), IsAdmin())
async def cq_svc_num_start(query: CallbackQuery, state: FSMContext):
    """Ввод числового/текстового значения для поля сервиса."""
    parts = query.data.split(":")
    svc   = parts[2]
    field = parts[3]
    await state.set_state(Admin.edit_service_value)
    await state.update_data(svc_edit_service=svc, svc_edit_field=field)
    label = _SERVICE_FIELD_LABELS.get(field, field)
    hint = "Введите новое значение (число):" if field != 'api_key' else "Введите новый API ключ (или «-» чтобы использовать ENV):"
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin:svc_edit:{svc}"))
    await query.message.edit_text(
        f"✏️ <b>{label}</b>\n{hint}",
        reply_markup=kb.as_markup(),
    )


@router.message(Admin.edit_service_value, IsAdmin(), ~F.text.startswith("/"))
async def process_svc_edit_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    svc   = user_data.get('svc_edit_service')
    field = user_data.get('svc_edit_field')
    raw   = (message.text or '').strip()

    if field == 'api_key':
        new_val = None if raw == '-' else raw
    else:
        try:
            new_val = int(raw)
            if new_val < 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Введите корректное целое число (≥ 0).")
            return

    await db.update_service_field(svc, field, new_val)
    await state.clear()
    label = _SERVICE_FIELD_LABELS.get(field, field)
    await message.answer(f"✅ <b>{label}</b> для <b>{_SERVICE_NAMES.get(svc, svc)}</b> обновлено.")

    cfg = await db.get_service_settings(svc)
    await message.answer(
        f"⚙️ <b>Настройки сервиса: {_SERVICE_NAMES.get(svc, svc)}</b>",
        reply_markup=get_admin_service_edit_kb(cfg),
    )



@router.callback_query(F.data.startswith("admin:svc_limit:"), IsAdmin())
async def cq_svc_limit_start(query: CallbackQuery, state: FSMContext):
    stage = int(query.data.split(":")[2])
    await state.set_state(Admin.edit_op_limit_value)
    await state.update_data(op_limit_stage=stage)
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:services"))
    await query.message.edit_text(
        f"✏️ <b>Максимум ресурсов для ОП Этап-{stage}</b>\nВведите число:",
        reply_markup=kb.as_markup(),
    )


@router.message(Admin.edit_op_limit_value, IsAdmin(), ~F.text.startswith("/"))
async def process_op_limit_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    stage = user_data.get('op_limit_stage', 1)
    try:
        new_val = int((message.text or '').strip())
        if new_val < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное целое число (≥ 1).")
        return

    await db.set_op_stage_limit(stage, new_val)
    await state.clear()
    await message.answer(f"✅ Лимит ОП Этап-{stage} установлен: <b>{new_val}</b>.")

    cfgs = await db.get_all_service_settings()
    s1 = await db.get_op_stage_limit(1)
    s2 = await db.get_op_stage_limit(2)
    await message.answer(
        "⚙️ <b>Настройка источников ресурсов</b>",
        reply_markup=get_admin_services_menu_kb(cfgs, s1, s2),
    )



@router.callback_query(F.data == "admin:circles_menu", IsAdmin())
async def cq_circles_menu(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text(
        "🎥 <b>Кружки-приманки</b>\n\n"
        "<i>Первые кружки, которые видит новый пользователь (заданные тобой). "
        "Показываются по порядку до первой ОП. Можно задать «автора» и его контакт "
        "(раскрывается за звёзды).</i>",
        reply_markup=get_admin_circles_menu_kb(),
    )


@router.callback_query(F.data == "admin:add_bait_circle", IsAdmin())
async def cq_add_bait_circle(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Admin.add_bait_circle_video)
    await query.message.edit_text(
        "<b>Шаг 1/4:</b> Отправь видео-сообщение (кружок), которое будет приманкой.",
        reply_markup=get_admin_cancel_kb(),
    )
    await state.update_data(_wiz_msg=query.message.message_id)


@router.message(Admin.add_bait_circle_video, F.video_note, IsAdmin())
async def process_bait_video(message: Message, state: FSMContext):
    await state.update_data(bait_file_id=message.video_note.file_id)
    await state.set_state(Admin.add_bait_circle_name)
    await _wiz_edit(message, state,
                    "<b>Шаг 2/4:</b> Введи имя «автора» (будет показано замаскированно, напр. <code>Аня</code>):",
                    reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_bait_circle_name, F.text, IsAdmin())
async def process_bait_name(message: Message, state: FSMContext):
    await state.update_data(bait_name=message.text.strip())
    await state.set_state(Admin.add_bait_circle_username)
    await _wiz_edit(message, state,
                    "<b>Шаг 3/4:</b> Контакт «автора» для раскрытия за звёзды — "
                    "юзернейм (<code>@user</code>) или ссылка (https://...). Отправь «-» если без контакта:",
                    reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_bait_circle_username, F.text, IsAdmin())
async def process_bait_username(message: Message, state: FSMContext):
    raw = message.text.strip()
    username, url = None, None
    if raw and raw != '-':
        if raw.startswith('http://') or raw.startswith('https://'):
            url = raw
        else:
            username = raw.lstrip('@')
    await state.update_data(bait_username=username, bait_url=url)
    await state.set_state(Admin.add_bait_circle_gender)
    await _wiz_edit(message, state, "<b>Шаг 4/4:</b> Для какой ленты этот кружок?",
                    reply_markup=get_admin_bait_gender_kb())


@router.callback_query(Admin.add_bait_circle_gender, F.data.startswith("admin:baitgender:"), IsAdmin())
async def process_bait_gender(query: CallbackQuery, state: FSMContext):
    gender = query.data.split(":")[2]
    data = await state.get_data()
    order = await db.next_bait_order()
    await db.add_circle(
        owner_id=None, file_id=data['bait_file_id'], is_bait=True, bait_order=order,
        fake_author_name=data.get('bait_name'), fake_author_username=data.get('bait_username'),
        fake_author_url=data.get('bait_url'), gender=gender,
    )
    await state.clear()
    await query.answer("✅ Приманка добавлена!", show_alert=True)
    circles = await db.get_bait_circles()
    await query.message.edit_text(f"Список приманок ({len(circles)}):",
                                  reply_markup=get_admin_bait_circles_list_kb(circles))


@router.callback_query(F.data == "admin:list_bait_circles", IsAdmin())
async def cq_list_bait_circles(query: CallbackQuery):
    circles = await db.get_bait_circles()
    await query.message.edit_text(f"Список приманок ({len(circles)}):",
                                  reply_markup=get_admin_bait_circles_list_kb(circles))


@router.callback_query(F.data.startswith("admin:delete_bait:"), IsAdmin())
async def cq_delete_bait(query: CallbackQuery):
    cid = int(query.data.split(":")[2])
    await db.delete_circle(cid)
    await query.answer("Удалено!")
    circles = await db.get_bait_circles()
    await query.message.edit_text(f"Список приманок ({len(circles)}):",
                                  reply_markup=get_admin_bait_circles_list_kb(circles))


@router.callback_query(F.data.startswith("admin:preview_bait:"), IsAdmin())
async def cq_preview_bait(query: CallbackQuery, bot: Bot):
    cid = int(query.data.split(":")[2])
    circle = await db.get_circle(cid)
    if not circle:
        await query.answer("Не найдено.", show_alert=True)
        return
    await query.answer()
    try:
        await bot.send_video_note(query.from_user.id, video_note=circle['file_id'])
        contact = circle.get('fake_author_username') or circle.get('fake_author_url') or '—'
        await bot.send_message(query.from_user.id,
                               f"#{circle.get('bait_order')} автор: <b>{circle.get('fake_author_name')}</b>\nконтакт: {contact}")
    except Exception:
        await query.answer("Не удалось показать (битый file_id?).", show_alert=True)



@router.callback_query(F.data == "admin:bait_menu", IsAdmin())
async def cq_bait_menu(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text(
        "📨 <b>Байт-уведомления</b>\n\n"
        "<i>«у тебя новое видео-сообщение 👀» — приходит неактивным пользователям. "
        "Кнопка ведёт в просмотр кружков (и в ОП, если нужно).</i>\n\n"
        "У каждого поста своё случайное окно «От–До» (в минутах после последней активности). "
        "Каждый пост отправляется один раз; новая активность сбрасывает таймер.",
        reply_markup=get_admin_bait_menu_kb(),
    )


@router.callback_query(F.data == "admin:add_bait_msg", IsAdmin())
async def cq_add_bait_msg(query: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.add_bait_message_text)
    await query.message.edit_text(
        "<b>Шаг 1/3:</b> Введи текст байт-уведомления (напр. <code>у тебя новое видео-сообщение 👀</code>):",
        reply_markup=get_admin_cancel_kb(),
    )
    await state.update_data(_wiz_msg=query.message.message_id)


@router.message(Admin.add_bait_message_text, F.text, IsAdmin())
async def process_bait_msg_text(message: Message, state: FSMContext):
    await state.update_data(bait_msg_text=message.html_text)
    await state.set_state(Admin.add_bait_message_button)
    await _wiz_edit(message, state,
                    "<b>Шаг 2/3:</b> Текст кнопки (напр. <code>Посмотреть</code>) или «-» для значения по умолчанию:",
                    reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_bait_message_button, F.text, IsAdmin())
async def process_bait_msg_button(message: Message, state: FSMContext):
    btn = message.text.strip()
    if btn == '-' or not btn:
        btn = 'Посмотреть'
    await state.update_data(bait_msg_button=btn)
    await state.set_state(Admin.add_bait_message_delay)
    await _wiz_edit(message, state,
                    "<b>Шаг 3/3:</b> Через сколько минут после последней активности отправлять? "
                    "Задай диапазон «От-До» — бот выберет случайное время в нём.\n\n"
                    "Формат: <code>30-90</code> (или одно число для точной задержки):",
                    reply_markup=get_admin_cancel_kb())


@router.message(Admin.add_bait_message_delay, F.text, IsAdmin())
async def process_bait_msg_delay(message: Message, state: FSMContext):
    raw = message.text.strip().replace(' ', '')
    try:
        if '-' in raw:
            lo_s, hi_s = raw.split('-', 1)
            lo, hi = int(lo_s), int(hi_s)
        else:
            lo = hi = int(raw)
        if lo <= 0 or hi <= 0:
            raise ValueError
    except ValueError:
        await _wiz_edit(message, state,
                        "❌ Неверный формат. Пример: <code>30-90</code> или <code>60</code>. Введите снова:",
                        reply_markup=get_admin_cancel_kb())
        return
    if hi < lo:
        lo, hi = hi, lo
    data = await state.get_data()
    await db.add_bait_message(data['bait_msg_text'], data.get('bait_msg_button', 'Посмотреть'),
                              delay_min=lo, delay_max=hi)
    msgs = await db.get_bait_messages()
    await _wiz_edit(message, state,
                    f"✅ <b>Байт добавлен!</b> Окно: {lo}–{hi} мин.\n\nСписок байтов ({len(msgs)}):",
                    reply_markup=get_admin_bait_msg_list_kb(msgs))
    await state.clear()


@router.callback_query(F.data == "admin:list_bait_msg", IsAdmin())
async def cq_list_bait_msg(query: CallbackQuery):
    msgs = await db.get_bait_messages()
    await query.message.edit_text(f"Список байтов ({len(msgs)}):", reply_markup=get_admin_bait_msg_list_kb(msgs))


@router.callback_query(F.data.startswith("admin:delete_bait_msg:"), IsAdmin())
async def cq_delete_bait_msg(query: CallbackQuery):
    bid = int(query.data.split(":")[2])
    await db.delete_bait_message(bid)
    await query.answer("Удалено!")
    msgs = await db.get_bait_messages()
    await query.message.edit_text(f"Список байтов ({len(msgs)}):", reply_markup=get_admin_bait_msg_list_kb(msgs))



@router.callback_query(F.data == "admin:settings", IsAdmin())
async def cq_settings(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text(
        "💰 <b>Настройки и тексты</b>\n\n"
        "<i>Здесь меняется баланс ОП, награды, пакеты звёзд и тексты бота.</i>",
        reply_markup=get_admin_settings_menu_kb(),
    )


def _short(val: str, n: int = 22) -> str:
    val = (val or '').replace("\n", " ")
    return val if len(val) <= n else val[:n - 1] + "…"


@router.callback_query(F.data == "admin:set_economy", IsAdmin())
async def cq_set_economy(query: CallbackQuery, state: FSMContext):
    await state.clear()
    items = []
    for s in appcfg.ECONOMY_SETTINGS:
        val = await db.get_setting(s['key']) or s['default']
        items.append({'key': s['key'], 'label': s['label'], 'display': _short(val)})
    await query.message.edit_text(
        "💰 <b>Экономика и звёзды</b>\n\n"
        "<i>Пакеты задаются в формате <code>count:stars</code> через запятую "
        "(напр. <code>5:5,10:9,40:32</code>).</i>",
        reply_markup=get_admin_settings_list_kb(items),
    )


@router.callback_query(F.data == "admin:set_texts", IsAdmin())
async def cq_set_texts(query: CallbackQuery, state: FSMContext):
    await state.clear()
    items = []
    for s in appcfg.TEXT_SETTINGS:
        overridden = await db.get_setting(s['key'])
        items.append({'key': s['key'], 'label': s['label'],
                      'display': "изменён" if overridden else "стандарт"})
    await query.message.edit_text(
        "✏️ <b>Тексты бота</b>\n\n"
        "<i>В приветствии доступна подстановка <code>{name}</code> — имя пользователя. "
        "Можно использовать HTML и премиум-эмодзи.</i>",
        reply_markup=get_admin_settings_list_kb(items),
    )


@router.callback_query(F.data.startswith("admin:setedit:"), IsAdmin())
async def cq_setedit(query: CallbackQuery, state: FSMContext):
    from utils.texts import strip_html
    key = query.data.split(":", 2)[2]
    kind = _SETTING_KIND.get(key)
    if not kind:
        await query.answer("Неизвестная настройка.", show_alert=True)
        return
    await state.set_state(Admin.edit_setting_value)
    await state.update_data(setting_key=key)
    cur = await db.get_setting(key) or appcfg.default_for(key)
    group_cb = "admin:set_texts" if key in _TEXT_KEYS else "admin:set_economy"
    if kind == 'int':
        hint = "Введи целое число ≥ 0:"
    elif kind == 'pkg':
        hint = "Введи пакеты: <code>count:stars,count:stars</code> (напр. <code>5:5,10:9,40:32</code>):"
    else:
        hint = "Отправь новый текст (HTML/премиум-эмодзи поддерживаются). Отправь «-» чтобы сбросить к стандарту:"
    await query.message.edit_text(
        f"✏️ <b>{_SETTING_LABEL.get(key, key)}</b>\n\n"
        f"Текущее значение:\n<blockquote>{strip_html(cur)[:300]}</blockquote>\n\n{hint}",
        reply_markup=get_admin_setting_edit_kb(key, group_cb),
    )


@router.callback_query(F.data.startswith("admin:setreset:"), IsAdmin())
async def cq_setreset(query: CallbackQuery, state: FSMContext):
    key = query.data.split(":", 2)[2]
    await db.set_setting(key, appcfg.default_for(key))
    await state.clear()
    await query.answer("Сброшено к стандарту.", show_alert=True)
    if key in _TEXT_KEYS:
        await cq_set_texts(query, state)
    else:
        await cq_set_economy(query, state)


@router.message(Admin.edit_setting_value, F.text, IsAdmin())
async def process_setting_value(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get('setting_key')
    kind = _SETTING_KIND.get(key, 'int')

    if kind == 'int':
        raw = (message.text or '').strip()
        if not raw.lstrip('-').isdigit() or int(raw) < 0:
            await message.answer("❌ Введи целое число ≥ 0.")
            return
        value = str(int(raw))
    elif kind == 'pkg':
        raw = (message.text or '').strip()
        pkgs = appcfg.parse_packages(raw)
        if not pkgs:
            await message.answer("❌ Неверный формат. Пример: <code>5:5,10:9,40:32</code>")
            return
        value = ",".join(f"{c}:{s}" for c, s in pkgs)
    else:
        if (message.text or '').strip() == '-':
            value = appcfg.default_for(key)
        else:
            value = message.html_text

    await db.set_setting(key, value)
    await state.clear()
    await message.answer(f"✅ <b>{_SETTING_LABEL.get(key, key)}</b> обновлено.")
    group = "тексты" if key in _TEXT_KEYS else "экономику"
    await message.answer(
        f"Открой «💰 Настройки» → {group}, чтобы продолжить.",
        reply_markup=get_admin_main_menu_kb(await db.count_open_reports()),
    )



@router.callback_query(F.data == "admin:reports", IsAdmin())
async def cq_reports(query: CallbackQuery, state: FSMContext):
    await state.clear()
    reports = await db.get_reports('open', 30)
    text = f"🚩 <b>Открытые жалобы ({len(reports)})</b>" if reports else "🚩 Открытых жалоб нет."
    try:
        await query.message.edit_text(text, reply_markup=get_admin_reports_list_kb(reports))
    except Exception:
        await query.message.answer(text, reply_markup=get_admin_reports_list_kb(reports))


@router.callback_query(F.data.startswith("admin:report:"), IsAdmin())
async def cq_report_view(query: CallbackQuery, bot: Bot):
    rid = int(query.data.split(":")[2])
    report = await db.get_report(rid)
    if not report:
        await query.answer("Жалоба не найдена.", show_alert=True)
        return
    text = (
        f"🚩 <b>Жалоба #{rid}</b>\n\n"
        f"Тип: <b>{report['target_type']}</b>\n"
        f"Кружок ID: <b>{report.get('target_circle_id')}</b>\n"
        f"На пользователя: <b>{report.get('target_user_id')}</b>\n"
        f"От: <b>{report['reporter_id']}</b>\n"
        f"Причина: {report.get('reason') or '—'}"
    )
    await query.message.edit_text(text, reply_markup=get_admin_report_actions_kb(report))
    if report.get('target_circle_id'):
        circle = await db.get_circle(report['target_circle_id'])
        if circle:
            try:
                await bot.send_video_note(query.from_user.id, video_note=circle['file_id'])
            except Exception:
                pass


@router.callback_query(F.data.startswith("admin:rep_block_circle:"), IsAdmin())
async def cq_rep_block_circle(query: CallbackQuery, bot: Bot):
    rid = int(query.data.split(":")[2])
    report = await db.get_report(rid)
    if report and report.get('target_circle_id'):
        owner_id = await db.block_circle(report['target_circle_id'])
        if owner_id:
            try:
                from utils.texts import get_circle_blocked_notice
                await bot.send_message(owner_id, get_circle_blocked_notice())
            except Exception:
                pass
    await db.resolve_report(rid)
    await query.answer("Кружок заблокирован, жалоба закрыта.", show_alert=True)
    reports = await db.get_reports('open', 30)
    await query.message.edit_text(f"🚩 <b>Открытые жалобы ({len(reports)})</b>",
                                  reply_markup=get_admin_reports_list_kb(reports))


@router.callback_query(F.data.startswith("admin:rep_ban:"), IsAdmin())
async def cq_rep_ban(query: CallbackQuery):
    rid = int(query.data.split(":")[2])
    report = await db.get_report(rid)
    if report and report.get('target_user_id'):
        await db.set_user_banned(report['target_user_id'], True)
    await db.resolve_report(rid)
    await query.answer("Пользователь забанен, жалоба закрыта.", show_alert=True)
    reports = await db.get_reports('open', 30)
    await query.message.edit_text(f"🚩 <b>Открытые жалобы ({len(reports)})</b>",
                                  reply_markup=get_admin_reports_list_kb(reports))


@router.callback_query(F.data.startswith("admin:rep_resolve:"), IsAdmin())
async def cq_rep_resolve(query: CallbackQuery):
    rid = int(query.data.split(":")[2])
    await db.resolve_report(rid)
    await query.answer("Жалоба закрыта.")
    reports = await db.get_reports('open', 30)
    await query.message.edit_text(f"🚩 <b>Открытые жалобы ({len(reports)})</b>",
                                  reply_markup=get_admin_reports_list_kb(reports))



async def _from_moderation_channel(query: CallbackQuery) -> bool:
    """Клик пришёл из настроенного канала модерации? (этот канал приватный и доверенный)."""
    ch = await appcfg.get_moderation_channel_id()
    return bool(ch) and query.message is not None and query.message.chat.id == ch


async def _moderation_remove(query: CallbackQuery, bot: Bot, cid: int, ban: bool):
    owner_id = await db.block_circle(cid)
    if ban and owner_id:
        await db.set_user_banned(owner_id, True)
    if owner_id:
        try:
            from utils.texts import get_circle_blocked_notice
            await bot.send_message(owner_id, get_circle_blocked_notice())
        except Exception:
            pass
    label = "⛔ Убран из ленты, автор забанен" if ban else "🗑 Убран из ленты"
    await query.answer(label, show_alert=True)
    try:
        await query.message.edit_reply_markup(reply_markup=get_circle_moderation_done_kb(label))
    except Exception:
        pass


@router.callback_query(F.data.startswith("mod:del:"))
async def cq_mod_channel_del(query: CallbackQuery, bot: Bot):
    if not await _from_moderation_channel(query):
        await query.answer("Только из канала модерации.", show_alert=True)
        return
    cid = int(query.data.split(":")[2])
    await _moderation_remove(query, bot, cid, ban=False)


@router.callback_query(F.data.startswith("mod:delban:"))
async def cq_mod_channel_delban(query: CallbackQuery, bot: Bot):
    if not await _from_moderation_channel(query):
        await query.answer("Только из канала модерации.", show_alert=True)
        return
    cid = int(query.data.split(":")[2])
    await _moderation_remove(query, bot, cid, ban=True)



@router.callback_query(F.data == "admin:mod_channel", IsAdmin())
async def cq_mod_channel(query: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    from keyboards.inline_keyboards import get_admin_mod_channel_kb
    ch = await appcfg.get_moderation_channel_id()
    cur = "<i>не задан</i>"
    if ch:
        title = ""
        try:
            chat = await bot.get_chat(ch)
            if chat.title:
                title = f" — <b>{chat.title}</b>"
        except Exception:
            title = ""
        cur = f"<code>{ch}</code>{title}"
    await query.message.edit_text(
        "📡 <b>Канал модерации кружков</b>\n\n"
        f"Сейчас: {cur}\n\n"
        "Сюда дублируется каждый новый кружок с кнопками "
        "«🗑 Убрать из ленты» / «⛔ Убрать + бан». Бот должен быть <b>админом</b> этого канала.",
        reply_markup=get_admin_mod_channel_kb(),
    )


@router.callback_query(F.data == "admin:mod_channel_set", IsAdmin())
async def cq_mod_channel_set(query: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.set_moderation_channel)
    await query.message.edit_text(
        "Перешлите сюда любой пост из нужного канала (бот должен быть там админом) — "
        "я возьму его ID автоматически.\n\n"
        "Либо отправьте числовой ID канала вручную (формат <code>-100…</code>).",
        reply_markup=get_admin_cancel_kb(),
    )
    await state.update_data(_wiz_msg=query.message.message_id)


@router.message(Admin.set_moderation_channel)
async def process_set_moderation_channel(message: Message, state: FSMContext, bot: Bot):
    chat_id = None
    title = None
    fo = getattr(message, 'forward_origin', None)
    if fo is not None and getattr(fo, 'chat', None) is not None:
        chat_id, title = fo.chat.id, fo.chat.title
    elif getattr(message, 'forward_from_chat', None) is not None:
        chat_id, title = message.forward_from_chat.id, message.forward_from_chat.title
    elif message.text:
        try:
            chat_id = int(message.text.strip())
        except ValueError:
            chat_id = None

    if chat_id is None:
        await _wiz_edit(message, state,
                        "❌ Не понял. Перешлите пост <b>из канала</b> или отправьте числовой ID "
                        "(например <code>-1001234567890</code>):",
                        reply_markup=get_admin_cancel_kb())
        return

    try:
        await bot.send_message(chat_id, "✅ Канал модерации подключён. Сюда будут приходить кружки.")
    except Exception as e:
        await _wiz_edit(message, state,
                        "⚠️ Не получилось отправить в этот канал. Убедись, что бот добавлен туда "
                        f"<b>админом</b>, и попробуй снова:\n\n<code>{str(e)[:200]}</code>",
                        reply_markup=get_admin_cancel_kb())
        return

    await db.set_setting(appcfg.MOD_CHANNEL_KEY, str(chat_id))
    from keyboards.inline_keyboards import get_admin_mod_channel_kb
    label = f"<b>{title}</b> (<code>{chat_id}</code>)" if title else f"<code>{chat_id}</code>"
    await _wiz_edit(message, state,
                    f"✅ Канал модерации сохранён: {label}\n\n"
                    "Новые кружки и кнопки модерации теперь идут сюда.",
                    reply_markup=get_admin_mod_channel_kb())
    await state.clear()



_BC_MAX_BUTTONS = 10

_BC_INTRO = (
    "📢 <b>Рассылка</b>\n\n"
    "Отправьте или перешлите сюда сообщение, которое нужно разослать всем пользователям.\n"
    "Поддерживается текст, фото, видео, гифки, стикеры, кружки — с премиум-эмодзи.\n\n"
    "Дальше можно добавить кнопки-ссылки и посмотреть предпросмотр перед отправкой."
)


def _bc_compose_text(buttons: list) -> str:
    lines = ["📢 <b>Сообщение принято.</b>", ""]
    if buttons:
        lines.append(f"Кнопки ({len(buttons)}):")
        for b in buttons:
            lines.append(f"• {b['text']} → {b['url']}")
    else:
        lines.append("Кнопок пока нет.")
    lines.append("")
    lines.append("Добавьте кнопки-ссылки (по желанию) и нажмите «👁 Предпросмотр».")
    return "\n".join(lines)


@router.callback_query(F.data == "admin:broadcast", IsAdmin())
async def cq_broadcast_start(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_broadcast_cancel_kb
    await state.clear()
    await state.set_state(Admin.broadcast_message)
    await state.update_data(bc_buttons=[])
    await query.message.edit_text(_BC_INTRO, reply_markup=get_admin_broadcast_cancel_kb())
    await query.answer()


@router.message(Admin.broadcast_message, ~F.text.startswith("/"))
async def process_broadcast_message(message: Message, state: FSMContext):
    from utils.message_sender import serialize_message
    from keyboards.inline_keyboards import get_admin_broadcast_compose_kb
    from_chat_id = message.chat.id
    message_id = message.message_id
    message_json = serialize_message(message)
    await state.update_data(
        bc_from_chat_id=from_chat_id,
        bc_message_id=message_id,
        bc_message_json=message_json,
    )
    await state.set_state(Admin.broadcast_compose)
    data = await state.get_data()
    await message.answer(
        _bc_compose_text(data.get('bc_buttons', [])),
        reply_markup=get_admin_broadcast_compose_kb(len(data.get('bc_buttons', []))),
    )


@router.callback_query(F.data == "admin:bc_add_btn", IsAdmin())
async def cq_bc_add_btn(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_broadcast_cancel_kb
    data = await state.get_data()
    if len(data.get('bc_buttons', [])) >= _BC_MAX_BUTTONS:
        await query.answer(f"Максимум {_BC_MAX_BUTTONS} кнопок.", show_alert=True)
        return
    await state.set_state(Admin.broadcast_add_button)
    await query.message.edit_text(
        "Отправьте кнопку в формате:\n\n"
        "<code>Текст кнопки | https://ссылка</code>\n\n"
        "💡 Можно поставить премиум-эмодзи в начало текста — он станет иконкой кнопки.",
        reply_markup=get_admin_broadcast_cancel_kb(),
    )
    await query.answer()


@router.message(Admin.broadcast_add_button, F.text)
async def process_bc_add_button(message: Message, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_broadcast_compose_kb, get_admin_broadcast_cancel_kb
    clean_text, emoji_id = extract_icon_from_message(message)
    raw = (clean_text or "").strip()
    sep = '|' if '|' in raw else (' - ' if ' - ' in raw else None)
    if not sep:
        await message.answer(
            "❌ Не вижу разделитель. Формат: <code>Текст | https://ссылка</code>",
            reply_markup=get_admin_broadcast_cancel_kb(),
        )
        return
    label, url = raw.split(sep, 1)
    label, url = label.strip(), url.strip()
    if not label or not url.startswith(("http://", "https://")):
        await message.answer(
            "❌ Текст пустой или ссылка не начинается с http:// или https://. Попробуйте снова.",
            reply_markup=get_admin_broadcast_cancel_kb(),
        )
        return
    data = await state.get_data()
    buttons = list(data.get('bc_buttons', []))
    buttons.append({'text': label, 'url': url, 'icon_emoji_id': emoji_id})
    await state.update_data(bc_buttons=buttons)
    await state.set_state(Admin.broadcast_compose)
    await message.answer(
        _bc_compose_text(buttons),
        reply_markup=get_admin_broadcast_compose_kb(len(buttons)),
    )


@router.callback_query(F.data == "admin:bc_clear_btns", IsAdmin())
async def cq_bc_clear_btns(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_broadcast_compose_kb
    await state.update_data(bc_buttons=[])
    await query.message.edit_text(
        _bc_compose_text([]),
        reply_markup=get_admin_broadcast_compose_kb(0),
    )
    await query.answer("Кнопки убраны.")


@router.callback_query(F.data == "admin:bc_back_compose", IsAdmin())
async def cq_bc_back_compose(query: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import get_admin_broadcast_compose_kb
    await state.set_state(Admin.broadcast_compose)
    data = await state.get_data()
    buttons = data.get('bc_buttons', [])
    await query.message.edit_text(
        _bc_compose_text(buttons),
        reply_markup=get_admin_broadcast_compose_kb(len(buttons)),
    )
    await query.answer()


@router.callback_query(F.data == "admin:bc_preview", IsAdmin())
async def cq_bc_preview(query: CallbackQuery, state: FSMContext, bot: Bot):
    from keyboards.inline_keyboards import build_broadcast_markup, get_admin_broadcast_confirm_kb
    data = await state.get_data()
    if not data.get('bc_message_id'):
        await query.answer("Сессия истекла, начните заново.", show_alert=True)
        return
    buttons = data.get('bc_buttons', [])
    markup = build_broadcast_markup(buttons)
    sent = await send_stored_message(
        bot=bot,
        chat_id=query.from_user.id,
        from_chat_id=data['bc_from_chat_id'],
        message_id=data['bc_message_id'],
        msg_json_raw=data.get('bc_message_json'),
        override_markup=markup,
        label="broadcast_preview",
    )
    if not sent:
        await query.answer("Не удалось показать предпросмотр.", show_alert=True)
        return
    total = len(await db.get_all_user_ids())
    await state.set_state(Admin.broadcast_confirm)
    await query.message.answer(
        f"☝️ Так будет выглядеть рассылка.\n\n"
        f"Получателей: <b>{total}</b>. Отправить?",
        reply_markup=get_admin_broadcast_confirm_kb(),
    )
    await query.answer()


@router.callback_query(F.data == "admin:bc_send", IsAdmin())
async def cq_bc_send(query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if not data.get('bc_message_id'):
        await query.answer("Сессия истекла, начните заново.", show_alert=True)
        return
    from_chat_id = data['bc_from_chat_id']
    message_id = data['bc_message_id']
    message_json = data.get('bc_message_json')
    buttons = data.get('bc_buttons', [])
    await state.clear()
    await query.message.edit_text("📢 Рассылка запускается…")
    await query.answer()
    asyncio.create_task(_broadcast_worker(
        bot=bot,
        control_chat_id=query.message.chat.id,
        control_msg_id=query.message.message_id,
        from_chat_id=from_chat_id,
        message_id=message_id,
        message_json=message_json,
        buttons=buttons,
    ))


async def _broadcast_worker(bot: Bot, control_chat_id: int, control_msg_id: int,
                            from_chat_id: int, message_id: int, message_json, buttons: list):
    from keyboards.inline_keyboards import build_broadcast_markup
    markup = build_broadcast_markup(buttons)
    user_ids = await db.get_all_user_ids()
    total = len(user_ids)
    sent = failed = 0

    async def _update(text: str):
        try:
            await bot.edit_message_text(chat_id=control_chat_id, message_id=control_msg_id, text=text)
        except Exception:
            pass

    if total == 0:
        await _update("📢 Рассылка завершена: получателей нет.")
        return

    for i, uid in enumerate(user_ids, 1):
        try:
            ok = await send_stored_message(
                bot=bot,
                chat_id=uid,
                from_chat_id=from_chat_id,
                message_id=message_id,
                msg_json_raw=message_json,
                override_markup=markup,
                label="broadcast",
            )
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception as e:
            failed += 1
            logging.error(f"[Broadcast] send to {uid} failed: {e}")
        await asyncio.sleep(0.05)
        if i % 25 == 0 or i == total:
            await _update(
                "📢 <b>Рассылка идёт…</b>\n\n"
                f"📦 Обработано: {i}/{total}\n"
                f"✅ Доставлено: {sent}\n"
                f"❌ Не доставлено: {failed}"
            )

    await _update(
        "✅ <b>Рассылка завершена.</b>\n\n"
        f"👥 Всего: {total}\n"
        f"✅ Доставлено: {sent}\n"
        f"❌ Не доставлено (блокировки и т.п.): {failed}"
    )