
import re
import random
from typing import Dict, List, Optional

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, \
    CopyTextButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import json

import config
from database.db_instance import db
from utils.texts import E, strip_html


class MenuCallback(CallbackData, prefix="menu"): action: str


class GiftCallback(CallbackData, prefix="gift"):
    name: str
    emoji: str
    emoji_id: str = ""


class GameCallback(CallbackData, prefix="game"): action: str; index: int = None


_VALID_STYLES = ("primary", "success", "danger")


def _ib(text: str, icon_id: str = None, style: str = None, **kwargs) -> InlineKeyboardButton:
    """Кнопка с premium-иконкой и цветом: поля icon_custom_emoji_id/style нестандартные, нужен пропатченный Bot API."""
    if icon_id:
        kwargs['icon_custom_emoji_id'] = icon_id
    if style in _VALID_STYLES:
        kwargs['style'] = style
    return InlineKeyboardButton(text=text, **kwargs)


def _extract_custom_emoji_id(text: str):
    """Достаёт custom emoji id из <tg-emoji> в названии канала: (текст, emoji_id|None)."""
    pattern = r'<tg-emoji emoji-id="(\d+)">[^<]*</tg-emoji>'
    match = re.search(pattern, text)
    if match:
        clean_text = re.sub(pattern, '', text).strip()
        return clean_text, match.group(1)
    return text, None


async def add_special_button(builder: InlineKeyboardBuilder, location: str):
    """
    Добавляет рекламную кнопку-ссылку на экран. Активных кнопок может быть
    несколько — для данного экрана выбирается СЛУЧАЙНАЯ из подходящих.
    location — один из реальных экранов Кружок-бота:
        'feed'     — под кружком в ленте
        'profile'  — профиль
        'referral' — экран «Пригласить друга»
        'purchase' — экраны покупок (просмотры / авторы / загрузки)
    """
    active = await db.get_active_special_ad_buttons()
    candidates = [
        b for b in active
        if b.get(f"show_in_{location}") and b.get("text") and b.get("url")
    ]
    if candidates:
        chosen = random.choice(candidates)
        icon_id = chosen.get("icon_emoji_id")
        style = chosen.get("button_style") or "primary"
        builder.row(_ib(chosen["text"], icon_id=icon_id, style=style, url=chosen["url"]))
        return
    if not active and getattr(config, "SPECIAL_BUTTON_URL", None):
        btn_text = getattr(config, "SPECIAL_BUTTON_TEXT", "💫 Забрать подарок 🎉")
        builder.row(_ib(btn_text, style="primary", url=config.SPECIAL_BUTTON_URL))



BTN_WATCH    = "Смотреть кружки"
BTN_FEED     = "Лента"
BTN_PROFILE  = "Профиль"
BTN_INVITE   = "Пригласить друга"
BTN_TASKS    = "Задания"
BTN_ANON     = "Анонимный чат"


def _rb(text: str, icon_id: str = None, style: str = None) -> KeyboardButton:
    """Reply-кнопка с премиум-иконкой и цветом (Bot API 9.4: primary/success/danger)."""
    kw = {'text': text}
    if icon_id:
        kw['icon_custom_emoji_id'] = icon_id
    if style in _VALID_STYLES:
        kw['style'] = style
    return KeyboardButton(**kw)


def get_main_reply_kb(views_count: int) -> ReplyKeyboardMarkup:
    """Нижняя reply-клавиатура — главная навигация (премиум-иконки + цвета)."""
    rows = [
        [_rb(f"{BTN_WATCH} ({views_count})", "5285165181389777639", "success")],
        [_rb(BTN_ANON, "5224415424493398515", "primary")],
        [_rb(BTN_FEED, "5309974037772928528", "primary"),
         _rb(BTN_PROFILE, "5231200819986047254", "primary")],
        [_rb(BTN_INVITE, "5292108060448271166", "danger"),
         _rb(BTN_TASKS, "5362006552951690043", "danger")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_start_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Смотреть кружки", icon_id="5285165181389777639", style="success",
                    callback_data="circle:next"))
    return builder.as_markup()


def get_start_gender_kb() -> InlineKeyboardMarkup:
    """Выбор пола на старте (просто сохраняется)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _ib("Я парень", icon_id="5292108060448271166", style="primary", callback_data="start:gender:male"),
        _ib("Я девушка", icon_id="5291764338510538167", style="primary", callback_data="start:gender:female"),
    )
    return builder.as_markup()


def get_start_feed_kb() -> InlineKeyboardMarkup:
    """Выбор ленты кружков на старте (мужские / женские / любые)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _ib("Мужские", icon_id="5292108060448271166", style="primary", callback_data="start:feed:male"),
        _ib("Женские", icon_id="5291764338510538167", style="primary", callback_data="start:feed:female"),
    )
    builder.row(_ib("Любые", icon_id="5292108060448271166", style="secondary", callback_data="start:feed:any"))
    return builder.as_markup()


_OP_CHANNEL_EMOJI_IDS = [
    "5368323483476440901",
    "5368804889180779889",
    "5368834975426688973",
    "5368728967043891035",
    "5370629764950273780",
    "5370915878491665291",
]


def get_subscription_channels_kb(channels: list, check_callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for channel in channels:
        channel_url = channel.get('url')
        if channel_url:
            builder.row(_ib(
                "Подписаться",
                icon_id=random.choice(_OP_CHANNEL_EMOJI_IDS),
                style="primary",
                url=channel_url
            ))
    builder.row(_ib("Проверить подписку",
                    icon_id="5429501538806548545",
                    style="success",
                    callback_data=check_callback_data))
    return builder.as_markup()


async def get_circle_kb(circle: dict, revealed: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура под кружком: реакции, узнать автора, жалоба, следующий."""
    cid = circle['id']
    likes = circle.get('likes', 0)
    dislikes = circle.get('dislikes', 0)
    builder = InlineKeyboardBuilder()
    builder.row(
        _ib(f"{likes}", icon_id="5370915878491665291", style="primary", callback_data=f"circle:like:{cid}"),
        _ib(f"{dislikes}", icon_id="5447644880824181073", style="secondary", callback_data=f"circle:dislike:{cid}"),
    )
    if not revealed:
        builder.row(_ib("Узнать автора", icon_id="5285165181389777639", style="primary",
                        callback_data=f"circle:reveal:{cid}"))
    builder.row(_ib("Пожаловаться", icon_id="5440660757194744323", style="danger",
                    callback_data=f"circle:report:{cid}"))
    builder.row(_ib("Следующий кружок", icon_id="5298640276208756843", style="success",
                    callback_data="circle:next"))
    await add_special_button(builder, "feed")
    return builder.as_markup()


def get_feed_settings_kb(current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    def mark(g, label):
        return ("• " if current == g else "") + label

    builder.row(
        _ib(mark('any', "Любой"), icon_id="5292108060448271166", style="primary", callback_data="feed:set:any"),
        _ib(mark('male', "Мужские"), icon_id="5292108060448271166", style="primary", callback_data="feed:set:male"),
        _ib(mark('female', "Женские"), icon_id="5291764338510538167", style="primary", callback_data="feed:set:female"),
    )
    builder.row(_ib("Закрыть", icon_id="5440660757194744323", callback_data="feed:close"))
    return builder.as_markup()


async def get_profile_kb(hide_authorship: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Смотреть кружки", icon_id="5285165181389777639", style="success", callback_data="circle:next"))
    builder.row(
        _ib("Записать кружок", icon_id="5355012477883004708", style="success", callback_data="circle:record"),
        _ib("Мои кружки", icon_id="5305663058838835096", style="primary", callback_data="mycircles:open"),
    )
    builder.row(
        _ib("Мой лучший кружок", icon_id="5305663058838835096", style="primary", callback_data="profile:best"),
        _ib("Топ кружков", icon_id="5217822164362739968", style="primary", callback_data="profile:top"),
    )
    if hide_authorship:
        hide_label, hide_style = "Авторство скрыто", "danger"
    else:
        from utils.app_config import get_int
        cost = await get_int('hide_authorship_cost')
        hide_label, hide_style = f"Скрыть авторство ({cost}⭐)", "secondary"
    builder.row(_ib(hide_label, icon_id="5821453562680448557", style=hide_style, callback_data="profile:hide_toggle"))
    builder.row(_ib("Пригласить друга", icon_id="5292108060448271166", style="primary", callback_data="menu:referrals"))
    builder.row(
        _ib("Купить просмотры", icon_id="5267500801240092311", style="success", callback_data="buy:views"),
        _ib("Купить авторов", icon_id="5285165181389777639", style="primary", callback_data="buy:authors"),
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ Правила", callback_data="info:rules"),
        InlineKeyboardButton(text="❓ FAQ", callback_data="info:faq"),
    )
    await add_special_button(builder, "profile")
    return builder.as_markup()


async def get_referral_kb(ref_link: str, share_text: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _ib("Скопировать", icon_id="5283140173029199387", style="primary",
            copy_text=CopyTextButton(text=ref_link)),
        _ib("Поделиться", icon_id="5298640276208756843", style="primary",
            switch_inline_query=share_text),
    )
    await add_special_button(builder, "referral")
    return builder.as_markup()


async def get_buy_views_kb() -> InlineKeyboardMarkup:
    from utils.app_config import get_view_packages
    builder = InlineKeyboardBuilder()
    for count, stars in await get_view_packages():
        builder.row(_ib(f"{count} просмотров — {stars}⭐️", icon_id="5267500801240092311",
                        style="primary", callback_data=f"buyviews:{count}:{stars}"))
    builder.row(_ib("Узнать автора", icon_id="5285165181389777639", style="secondary", callback_data="buy:authors"))
    builder.row(_ib("Назад в профиль", icon_id="5465144256920324180", callback_data="profile:open"))
    await add_special_button(builder, "purchase")
    return builder.as_markup()


async def get_buy_authors_kb() -> InlineKeyboardMarkup:
    from utils.app_config import get_author_packages
    builder = InlineKeyboardBuilder()
    for count, stars in await get_author_packages():
        builder.row(_ib(f"{count} автор(ов) — {stars}⭐️", icon_id="5267500801240092311",
                        style="primary", callback_data=f"buyauthors:{count}:{stars}"))
    builder.row(_ib("Просмотры кружков", icon_id="5285165181389777639", style="secondary", callback_data="buy:views"))
    builder.row(_ib("Назад в профиль", icon_id="5465144256920324180", callback_data="profile:open"))
    await add_special_button(builder, "purchase")
    return builder.as_markup()


def get_reveal_buy_kb(circle_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Купить просмотры авторов", icon_id="5267500801240092311", style="success",
                    callback_data="buy:authors"))
    builder.row(_ib("Назад к кружку", icon_id="5465144256920324180", callback_data="circle:next"))
    return builder.as_markup()


def get_my_circles_kb(circles: list) -> InlineKeyboardMarkup:
    """Список своих кружков с кнопками удаления (+ возврат в профиль)."""
    builder = InlineKeyboardBuilder()
    for i, c in enumerate(circles, 1):
        g = {'any': '👥', 'male': '♂', 'female': '♀'}.get(c.get('gender', 'any'), '👥')
        builder.row(
            _ib(f"#{i} {g} ❤{c.get('likes', 0)} · 👁{c.get('views', 0)}",
                icon_id="5305663058838835096", callback_data="noop"),
            _ib("Удалить", icon_id="5440660757194744323", style="danger",
                callback_data=f"mycircles:del:{c['id']}"),
        )
    builder.row(_ib("Записать кружок", icon_id="5355012477883004708", style="success", callback_data="circle:record"))
    builder.row(_ib("Назад в профиль", icon_id="5465144256920324180", callback_data="profile:open"))
    return builder.as_markup()


async def get_buy_uploads_kb() -> InlineKeyboardMarkup:
    from utils.app_config import get_upload_packages
    builder = InlineKeyboardBuilder()
    for count, stars in await get_upload_packages():
        builder.row(_ib(f"{count} загрузок — {stars}⭐️", icon_id="5397916757333654639",
                        style="primary", callback_data=f"buyuploads:{count}:{stars}"))
    builder.row(_ib("Назад в профиль", icon_id="5465144256920324180", callback_data="profile:open"))
    await add_special_button(builder, "purchase")
    return builder.as_markup()


def get_record_gender_kb() -> InlineKeyboardMarkup:
    """Выбор ленты для своего кружка (пользовательская запись)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _ib("Мужская", icon_id="5292108060448271166", style="primary", callback_data="record:gender:male"),
        _ib("Женская", icon_id="5291764338510538167", style="primary", callback_data="record:gender:female"),
    )
    builder.row(_ib("Любая", icon_id="5292108060448271166", style="secondary", callback_data="record:gender:any"))
    builder.row(_ib("Отмена", icon_id="5440660757194744323", style="danger", callback_data="record:cancel"))
    return builder.as_markup()


def get_top_circles_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Смотреть кружки", icon_id="5285165181389777639", style="success", callback_data="circle:next"))
    return builder.as_markup()


ANON_CANCEL = "Отмена поиска"
ANON_NEXT   = "Следующий собеседник"
ANON_STOP   = "Завершить диалог"
ANON_REVEAL = "Узнать собеседника"
ANON_REPORT = "Пожаловаться"


def get_anon_search_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_rb(ANON_CANCEL, "5440660757194744323", "danger")]],
        resize_keyboard=True,
    )


def get_anon_chat_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_rb(ANON_NEXT, "5298640276208756843", "success"),
             _rb(ANON_STOP, "5440660757194744323", "danger")],
            [_rb(ANON_REVEAL, "5285165181389777639", "primary"),
             _rb(ANON_REPORT, "5307535174953627548", "danger")],
        ],
        resize_keyboard=True,
    )


def get_anon_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Найти собеседника", icon_id="5285165181389777639", style="success", callback_data="anon:find"))
    builder.row(_ib("Изменить пол/возраст", icon_id="5283140173029199387", style="secondary", callback_data="anon:profile"))
    return builder.as_markup()


def get_anon_setup_gender_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _ib("Мужской", icon_id="5292108060448271166", style="primary", callback_data="anonsetup:male"),
        _ib("Женский", icon_id="5291764338510538167", style="primary", callback_data="anonsetup:female"),
    )
    return builder.as_markup()


def get_anon_reveal_buy_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Купить просмотры авторов", icon_id="5267500801240092311", style="success", callback_data="buy:authors"))
    return builder.as_markup()


def get_anon_after_chat_kb() -> InlineKeyboardMarkup:
    """Клавиатура после завершения диалога: узнать контакт собеседника / закрыть."""
    builder = InlineKeyboardBuilder()
    builder.row(_ib("Узнать контакт собеседника", icon_id="5285165181389777639",
                    style="success", callback_data="anon:reveal_last"))
    builder.row(_ib("Закрыть", icon_id="5440660757194744323", callback_data="anon:after_close"))
    return builder.as_markup()


def get_admin_main_menu_kb(open_reports: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎥 Кружки-приманки",         callback_data="admin:circles_menu")
    rep_label = f"🚩 Жалобы ({open_reports})" if open_reports else "🚩 Жалобы"
    builder.button(text=rep_label,                     callback_data="admin:reports")
    builder.button(text="📡 Канал модерации",          callback_data="admin:mod_channel")
    builder.button(text="📨 Байт-уведомления",        callback_data="admin:bait_menu")
    builder.button(text="🔧 Управление ОП",           callback_data="admin:op_management")
    builder.button(text="✍️ Задания",                  callback_data="admin:tasks_menu")
    builder.button(text="👋 Приветки",                 callback_data="admin:greetings_menu")
    builder.button(text="🔗 Рекламные кнопки",        callback_data="admin:special_button_menu")
    builder.button(text="⚡️ Реклама в ленте",        callback_data="admin:shows_d_menu")
    builder.button(text="📺 Реклама по таймеру",      callback_data="admin:shows_n_menu")
    builder.button(text="📢 Рассылка",                callback_data="admin:broadcast")
    builder.button(text="⚙️ Сервисы (ОП)",            callback_data="admin:services")
    builder.button(text="💰 Настройки / тексты",       callback_data="admin:settings")
    builder.button(text="📊 Статистика",              callback_data="admin:stats")
    builder.button(text="📈 Рекл-ссылки",             callback_data="admin:ad_links")
    builder.button(text="📂 Выгрузка пользователей",  callback_data="admin:export_users")
    builder.button(text="👮 Администраторы",          callback_data="admin:admins")
    builder.adjust(2)
    return builder.as_markup()


def get_admin_admins_kb(admins: List[Dict], can_manage: bool = True) -> InlineKeyboardMarkup:
    """Список динамических админов с кнопками снятия. super-админы из .env тут не показываются."""
    builder = InlineKeyboardBuilder()
    for a in admins:
        uid = a['user_id']
        uname = a.get('username')
        name = a.get('first_name') or 'без имени'
        label = f"@{uname}" if uname else f"{name} ({uid})"
        builder.row(
            InlineKeyboardButton(text=f"👤 {label}", callback_data="noop"),
            InlineKeyboardButton(text="❌ Снять", callback_data=f"admin:admin_remove:{uid}"),
        )
    if can_manage:
        builder.row(InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin:admin_add"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_tasks_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить задание", callback_data="admin:add_task")
    builder.button(text="📋 Список заданий",  callback_data="admin:list_tasks")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_greetings_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить приветку", callback_data="admin:add_greeting")
    builder.button(text="📋 Список приветок",   callback_data="admin:list_greetings")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_shows_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить показ", callback_data="admin:add_show")
    builder.button(text="📋 Список показов", callback_data="admin:list_shows")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_shows_list_kb(shows: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not shows:
        builder.button(text="Показов пока нет", callback_data="noop")

    target_labels = {
        'all': '🌍 Всем',
        'passed_op': '✅ Прошедшим ОП',
        'not_passed_op': '❌ Не прошедшим ОП'
    }

    for show in shows:
        target_label = target_labels.get(show.get('target_audience', 'all'), '🌍 Всем')
        delay_minutes = show.get('delay_minutes', 0)
        if delay_minutes < 60:
            delay_str = f"{delay_minutes} мин"
        else:
            hours = delay_minutes // 60
            minutes = delay_minutes % 60
            delay_str = f"{hours}ч {minutes}м" if minutes else f"{hours}ч"

        builder.button(
            text=f"ID {show['id']} — {delay_str} — {target_label}",
            callback_data=f"admin:preview_show:{show['id']}"
        )
        builder.button(text="❌ Удалить", callback_data=f"admin:delete_show:{show['id']}")

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:shows_menu"))
    return builder.as_markup()


def get_admin_show_target_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌍 Всем пользователям",       callback_data="admin_show_target:all")
    builder.button(text="✅ Только прошедшим ОП",      callback_data="admin_show_target:passed_op")
    builder.button(text="❌ Только не прошедшим ОП",   callback_data="admin_show_target:not_passed_op")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_greetings_list_kb(greetings: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not greetings:
        builder.button(text="Пока нет приветок", callback_data="noop")
    for g in greetings:
        builder.row(InlineKeyboardButton(
            text=f"ID {g['id']} · показов: {g.get('display_count', 0)} · 👁 превью",
            callback_data=f"admin:preview_greet:{g['id']}"))
        builder.row(
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"admin:edit_greet:{g['id']}"),
            InlineKeyboardButton(text="❌ Удалить",        callback_data=f"admin:delete_greet:{g['id']}"),
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:greetings_menu"))
    return builder.as_markup()


def get_admin_greeting_compose_kb(buttons_count: int, is_edit: bool = False) -> InlineKeyboardMarkup:
    """Меню сборки приветки: кнопки-ссылки / заменить сообщение / предпросмотр / сохранить."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить кнопку-ссылку", callback_data="admin:greet_add_btn")
    if buttons_count:
        builder.button(text=f"🗑 Убрать кнопки ({buttons_count})", callback_data="admin:greet_clear_btns")
    builder.button(text="🔄 Заменить сообщение", callback_data="admin:greet_replace_msg")
    builder.button(text="👁 Предпросмотр", callback_data="admin:greet_preview")
    builder.button(text="💾 Сохранить", callback_data="admin:greet_save")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:greetings_menu"))
    return builder.as_markup()


def get_admin_tasks_list_kb(tasks: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not tasks:
        builder.button(text="Заданий пока не добавлено", callback_data="noop")
    for task in tasks:
        valid = bool(task.get('url', '').startswith(('http://', 'https://')))
        title = f"{task['name']} (+{task['reward_attempts']})" if valid else f"⚠️ {task['name']} (битая ссылка)"
        builder.row(
            InlineKeyboardButton(text=f"{title} · 👁", callback_data=f"admin:view_task:{task['id']}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"admin:delete_task:{task['id']}"),
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:tasks_menu"))
    return builder.as_markup()


def get_admin_task_view_kb(task_id: int, url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if url and url.startswith(('http://', 'https://')):
        builder.row(InlineKeyboardButton(text="🔗 Открыть ссылку", url=url))
    builder.row(InlineKeyboardButton(text="❌ Удалить задание", callback_data=f"admin:delete_task:{task_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ К списку", callback_data="admin:list_tasks"))
    return builder.as_markup()


async def get_ad_links_list_kb(links: List[dict], page: int = 1, per_page: int = 10,
                                total: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for link in links:
        builder.button(text=f"📊 {link['name']}",
                       callback_data=f"admin:ad_stats:{link['id']}:{link['name']}")
    builder.adjust(1)

    if total is not None:
        total_pages = max(1, (total + per_page - 1) // per_page)
        prev_page = max(1, page - 1)
        next_page = min(total_pages, page + 1)
        builder.row(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin:ad_links_page:{prev_page}:{per_page}"),
            InlineKeyboardButton(text=f"Стр. {page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"admin:ad_links_page:{next_page}:{per_page}")
        )

    builder.row(InlineKeyboardButton(text="➕ Создать новую ссылку", callback_data="admin:add_ad_link"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в админку",     callback_data="admin:main_menu"))
    return builder.as_markup()


def get_ad_link_stats_kb(link_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Удалить эту ссылку",  callback_data=f"admin:del_ad_link_ask:{link_id}")
    builder.button(text="⬅️ К списку ссылок",    callback_data="admin:ad_links")
    builder.adjust(1)
    return builder.as_markup()


def get_ad_link_delete_confirm_kb(link_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить", callback_data=f"admin:delete_ad_link:{link_id}")
    builder.button(text="⬅️ Отмена",      callback_data="admin:ad_links")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_op_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить канал",  callback_data="admin:add_channel")
    builder.button(text="📋 Список каналов", callback_data="admin:list_channels")
    builder.button(text="👤 Вайтлист",       callback_data="admin:whitelist")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    builder.adjust(2)
    return builder.as_markup()


def get_admin_check_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Проверка подписки", callback_data="admin_check:membership")
    builder.button(text="⌛️ Проверка заявки",  callback_data="admin_check:join_request")
    builder.button(text="🚫 Без проверки",      callback_data="admin_check:none")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_premium_target_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Только премиумам",     callback_data="admin_premium:premium")
    builder.button(text="👤 Только НЕ премиумам",  callback_data="admin_premium:non_premium")
    builder.button(text="🌍 Всем пользователям",   callback_data="admin_premium:all")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_fsm"))
    return builder.as_markup()


_CHECK_TYPE_LABELS = {
    'membership':   '✅ проверка подписки',
    'join_request': '⌛️ проверка заявки',
    'none':         '🚫 без проверки',
    'subgram':      'SubGram',
    'botohub':      'BotoHub',
}


def get_admin_channel_list_kb(channels: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not channels:
        builder.button(text="Каналов пока не добавлено", callback_data="noop")
    for channel in channels:
        premium_icon = {'all': '🌍', 'premium': '💎', 'non_premium': '👤'}.get(
            channel.get('premium_target', 'all'), '🌍')
        builder.row(
            InlineKeyboardButton(
                text=f"{premium_icon} {channel['name']} · 👁",
                callback_data=f"admin:view_channel:{channel['id']}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"admin:delete_channel:{channel['id']}"),
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:op_management"))
    return builder.as_markup()


def get_admin_channel_view_kb(channel_id: int, url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if url:
        builder.row(InlineKeyboardButton(text="🔗 Открыть канал", url=url))
    builder.row(InlineKeyboardButton(text="❌ Удалить канал", callback_data=f"admin:delete_channel:{channel_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ К списку", callback_data="admin:list_channels"))
    return builder.as_markup()


def get_admin_subgram_mode_kb(current_mode: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    def label(mode: str, text: str) -> str:
        return ("✅ " if current_mode == mode else "") + text

    builder.button(text=label("both",        "На оба этапа (пополам)"),          callback_data="admin:set_subgram_mode:both")
    builder.button(text=label("first_only",  "Только этап 1 (все ресурсы)"),     callback_data="admin:set_subgram_mode:first_only")
    builder.button(text=label("second_only", "Только этап 2 (все ресурсы)"),     callback_data="admin:set_subgram_mode:second_only")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:op_management"))
    return builder.as_markup()


def get_admin_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:cancel_fsm")
    return builder.as_markup()



def get_admin_special_button_color_kb() -> InlineKeyboardMarkup:
    """Выбор цвета/стиля кнопки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔵 Синий (primary)",  callback_data="admin:sbcolor:primary")
    builder.button(text="🟢 Зелёный (success)", callback_data="admin:sbcolor:success")
    builder.button(text="🔴 Красный (danger)",  callback_data="admin:sbcolor:danger")
    builder.button(text="⚫ Серый (secondary)", callback_data="admin:sbcolor:secondary")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_fsm"))
    return builder.as_markup()


def get_admin_special_button_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить кнопку", callback_data="admin:add_special_button")
    builder.button(text="📋 Список кнопок",   callback_data="admin:list_special_buttons")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_special_button_positions_kb(
    show_in_feed: bool,
    show_in_profile: bool,
    show_in_referral: bool = False,
    show_in_purchase: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    def mark(flag: bool, text: str) -> str:
        return f"{'✅' if flag else '❌'} {text}"

    builder.button(text=mark(show_in_feed,     "Лента (под кружком)"),               callback_data="admin:sbpos:feed")
    builder.button(text=mark(show_in_profile,  "Профиль"),                           callback_data="admin:sbpos:profile")
    builder.button(text=mark(show_in_referral, "Пригласить друга"),                  callback_data="admin:sbpos:referral")
    builder.button(text=mark(show_in_purchase, "Экраны покупок"),                    callback_data="admin:sbpos:purchase")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="✅ Сохранить", callback_data="admin:sbpos:save"),
        InlineKeyboardButton(text="❌ Отмена",    callback_data="admin:cancel_fsm"),
    )
    return builder.as_markup()


def get_admin_special_buttons_list_kb(buttons: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not buttons:
        builder.button(text="Рекламных кнопок пока нет", callback_data="noop")
    for btn in buttons:
        active_icon = "✅" if btn.get('is_active') else "❌"
        builder.button(text=f"{active_icon} {btn['text']}",
                       callback_data=f"admin:toggle_special_button:{btn['id']}")
        builder.button(text="🗑 Удалить", callback_data=f"admin:delete_special_button:{btn['id']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:special_button_menu"))
    return builder.as_markup()



def get_admin_shows_d_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить рекламу", callback_data="admin:add_show_d")
    builder.button(text="📋 Список реклам",    callback_data="admin:list_shows_d")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_shows_d_list_kb(shows: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not shows:
        builder.button(text="Рекламы пока нет", callback_data="noop")
    for show in shows:
        active_icon = "✅" if show.get('is_active') else "❌"
        preview = _show_preview(show)
        builder.button(
            text=f"{active_icon} ID {show['id']} — {preview or 'без текста'} (показов: {show['display_count']})",
            callback_data=f"admin:preview_show_d:{show['id']}"
        )
        builder.button(text="❌ Удалить", callback_data=f"admin:delete_show_d:{show['id']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:shows_d_menu"))
    return builder.as_markup()



def get_admin_shows_n_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить рекламу", callback_data="admin:add_show_n")
    builder.button(text="📋 Список реклам",    callback_data="admin:list_shows_n")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_shows_n_list_kb(shows: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not shows:
        builder.button(text="Рекламы пока нет", callback_data="noop")

    for show in shows:
        active_icon = "✅" if show.get('is_active') else "❌"
        delay_minutes = show.get('delay_minutes', 0)
        if delay_minutes < 60:
            delay_str = f"{delay_minutes} мин"
        else:
            hours = delay_minutes // 60
            minutes = delay_minutes % 60
            delay_str = f"{hours}ч {minutes}м" if minutes else f"{hours}ч"
        preview = _show_preview(show)
        builder.button(
            text=f"{active_icon} ID {show['id']} — {delay_str} — {preview or 'без текста'} (показов: {show['display_count']})",
            callback_data=f"admin:preview_show_n:{show['id']}"
        )
        builder.button(text="❌ Удалить", callback_data=f"admin:delete_show_n:{show['id']}")

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:shows_n_menu"))
    return builder.as_markup()



_SERVICE_LABELS = {
    'admin':   '📋 Admin (свои каналы)',
    'subgram': '🔵 SubGram',
    'botohub': '🟠 BotoHub',
}


def get_admin_services_menu_kb(service_cfgs: List[Dict], stage1_limit: int, stage2_limit: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cfg in service_cfgs:
        svc = cfg['service']
        label = _SERVICE_LABELS.get(svc, svc)
        builder.button(text=label, callback_data=f"admin:svc_edit:{svc}")
    builder.adjust(1)
    builder.button(
        text=f"📊 Лимит каналов в ОП: {stage1_limit}  [Изменить]",
        callback_data="admin:svc_limit:1",
    )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_service_edit_kb(cfg: dict) -> InlineKeyboardMarkup:
    svc = cfg['service']
    builder = InlineKeyboardBuilder()

    def _tog(label: str, field: str, value: bool) -> InlineKeyboardButton:
        icon = "✅" if value else "❌"
        return InlineKeyboardButton(
            text=f"{icon} {label}",
            callback_data=f"admin:svc_tog:{svc}:{field}",
        )

    def _edit(label: str, field: str, val) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=f"✏️ {label}: {val}",
            callback_data=f"admin:svc_num:{svc}:{field}",
        )

    builder.row(_tog("ОП включена", "op1_enabled", cfg.get('op1_enabled', True)))
    builder.row(
        _edit("Макс каналов", "op1_max",      cfg.get('op1_max', 5)),
        _edit("Приоритет", "op1_priority", cfg.get('op1_priority', 10)),
    )
    builder.row(_tog("Задания", "tasks_enabled", cfg.get('tasks_enabled', True)))
    builder.row(
        _edit("Макс задания", "tasks_max",      cfg.get('tasks_max', 5)),
        _edit("Приоритет задания", "tasks_priority", cfg.get('tasks_priority', 10)),
    )
    if svc not in ('admin',):
        cur_key = cfg.get('api_key') or '(из ENV)'
        short = cur_key[:12] + '…' if len(cur_key) > 12 else cur_key
        builder.row(InlineKeyboardButton(
            text=f"🔑 API ключ: {short}",
            callback_data=f"admin:svc_num:{svc}:api_key",
        ))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:services"))
    return builder.as_markup()


def _show_preview(show: dict) -> str:
    """Короткое текстовое превью для записи показа."""
    try:
        msg_json = show.get('message_json')
        if isinstance(msg_json, str):
            msg_json = json.loads(msg_json)
        if isinstance(msg_json, dict):
            preview = msg_json.get('text') or msg_json.get('caption') or ""
            if not preview:
                if 'photo' in msg_json:
                    return "[Фото]"
                if 'animation' in msg_json:
                    return "[GIF/Анимация]"
                if 'video' in msg_json:
                    return "[Видео]"
            preview = preview.replace("\n", " ").strip()
            return preview[:30] + "…" if len(preview) > 30 else preview
    except Exception:
        pass
    return ""



def get_admin_circles_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить приманку", callback_data="admin:add_bait_circle")
    builder.button(text="📋 Список приманок",   callback_data="admin:list_bait_circles")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_bait_circles_list_kb(circles: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not circles:
        builder.button(text="Приманок пока нет", callback_data="noop")
    for c in circles:
        order = c.get('bait_order') or '?'
        name = c.get('fake_author_name') or 'без автора'
        g = {'any': '👥', 'male': '♂', 'female': '♀'}.get(c.get('gender', 'any'), '👥')
        builder.button(text=f"#{order} {g} {name} (👁 {c.get('views', 0)})",
                       callback_data=f"admin:preview_bait:{c['id']}")
        builder.button(text="❌ Удалить", callback_data=f"admin:delete_bait:{c['id']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:circles_menu"))
    return builder.as_markup()


def get_admin_bait_gender_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Любой",  callback_data="admin:baitgender:any")
    builder.button(text="♂ Мужской", callback_data="admin:baitgender:male")
    builder.button(text="♀ Женский", callback_data="admin:baitgender:female")
    builder.adjust(3)
    return builder.as_markup()


def get_admin_bait_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить пост",  callback_data="admin:add_bait_msg")
    builder.button(text="📋 Список постов",  callback_data="admin:list_bait_msg")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    builder.adjust(2)
    return builder.as_markup()


def get_admin_bait_msg_list_kb(messages: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not messages:
        builder.button(text="Постов пока нет", callback_data="noop")
    for m in messages:
        preview = (strip_html(m.get('text') or ''))[:24]
        rng = f"{m.get('delay_min', 30)}–{m.get('delay_max', 90)}м"
        builder.button(text=f"#{m['id']} ⏱{rng} {preview}", callback_data="noop")
        builder.button(text="❌ Удалить", callback_data=f"admin:delete_bait_msg:{m['id']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:bait_menu"))
    return builder.as_markup()


def get_admin_reports_list_kb(reports: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not reports:
        builder.button(text="Открытых жалоб нет", callback_data="noop")
    for r in reports:
        tt = '🎥' if r.get('target_type') == 'circle' else '👤'
        builder.button(text=f"#{r['id']} {tt} {(r.get('reason') or '')[:25]}",
                       callback_data=f"admin:report:{r['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_report_actions_kb(report: Dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rid = report['id']
    if report.get('target_circle_id'):
        builder.button(text="🚫 Заблокировать кружок", callback_data=f"admin:rep_block_circle:{rid}")
    if report.get('target_user_id'):
        builder.button(text="🔨 Забанить пользователя", callback_data=f"admin:rep_ban:{rid}")
    builder.button(text="✅ Отклонить (решено)", callback_data=f"admin:rep_resolve:{rid}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ К списку", callback_data="admin:reports"))
    return builder.as_markup()


def get_circle_moderation_kb(circle_id: int) -> InlineKeyboardMarkup:
    """Кнопки под кружком в канале модерации: убрать из ленты / убрать + бан автора."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Убрать из ленты",      callback_data=f"mod:del:{circle_id}")
    builder.button(text="⛔ Убрать + бан автора",   callback_data=f"mod:delban:{circle_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_circle_moderation_done_kb(label: str) -> InlineKeyboardMarkup:
    """Заглушка-результат после обработки кружка в канале модерации."""
    builder = InlineKeyboardBuilder()
    builder.button(text=label, callback_data="noop")
    return builder.as_markup()


def get_admin_mod_channel_kb() -> InlineKeyboardMarkup:
    """Раздел «Канал модерации»: задать/изменить канал."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Задать / изменить канал", callback_data="admin:mod_channel_set")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()



def get_admin_settings_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Экономика и звёзды", callback_data="admin:set_economy")
    builder.button(text="✏️ Тексты бота",         callback_data="admin:set_texts")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_settings_list_kb(items: List[Dict]) -> InlineKeyboardMarkup:
    """items: [{key,label,display}]"""
    builder = InlineKeyboardBuilder()
    for it in items:
        builder.button(text=f"{it['label']}: {it['display']}", callback_data=f"admin:setedit:{it['key']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:settings"))
    return builder.as_markup()


def get_admin_setting_edit_kb(key: str, group_cb: str, can_reset: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_reset:
        builder.button(text="↩️ Сбросить к стандарту", callback_data=f"admin:setreset:{key}")
    builder.button(text="❌ Отмена", callback_data=group_cb)
    builder.adjust(1)
    return builder.as_markup()



def get_admin_broadcast_compose_kb(buttons_count: int) -> InlineKeyboardMarkup:
    """Меню сборки рассылки: добавить кнопки / предпросмотр / отмена."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить кнопку-ссылку", callback_data="admin:bc_add_btn")
    if buttons_count:
        builder.button(text=f"🗑 Убрать кнопки ({buttons_count})", callback_data="admin:bc_clear_btns")
    builder.button(text="👁 Предпросмотр", callback_data="admin:bc_preview")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_broadcast_cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены рассылки (возврат в главное меню админки)."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:main_menu"))
    return builder.as_markup()


def get_admin_broadcast_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение запуска рассылки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Отправить всем", callback_data="admin:bc_send")
    builder.button(text="⬅️ Назад (к кнопкам)", callback_data="admin:bc_back_compose")
    builder.button(text="❌ Отмена", callback_data="admin:main_menu")
    builder.adjust(1)
    return builder.as_markup()


def build_broadcast_markup(buttons: List[Dict]) -> Optional[InlineKeyboardMarkup]:
    """Собирает inline-клавиатуру рассылки из списка {text, url, icon_emoji_id}."""
    if not buttons:
        return None
    builder = InlineKeyboardBuilder()
    for b in buttons:
        icon = b.get('icon_emoji_id')
        if icon:
            builder.row(_ib(b['text'], icon_id=icon, style='primary', url=b['url']))
        else:
            builder.row(InlineKeyboardButton(text=b['text'], url=b['url']))
    return builder.as_markup()
