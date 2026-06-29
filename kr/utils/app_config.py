"""
Конфигурируемые из админки настройки (хранятся в app_settings).
Числа, пакеты звёзд и тексты редактируются в разделе админки «⚙️ Настройки».
"""
from typing import List, Optional, Tuple

import config
from database.db_instance import db
from utils import texts
from utils.texts import E

MOD_CHANNEL_KEY = 'moderation_channel_id'


ECONOMY_SETTINGS = [
    {'key': 'free_initial_views',       'label': 'Стартовые просмотры',            'kind': 'int', 'default': '10'},
    {'key': 'ref_reward_views',         'label': 'Реф: +просмотров кружков',       'kind': 'int', 'default': '5'},
    {'key': 'ref_reward_author_views',  'label': 'Реф: +просмотров авторов',       'kind': 'int', 'default': '1'},
    {'key': 'op_min_interval',          'label': 'ОП: мин. просмотров',            'kind': 'int', 'default': '7'},
    {'key': 'op_max_interval',          'label': 'ОП: макс. просмотров',           'kind': 'int', 'default': '10'},
    {'key': 'author_reveal_cost',       'label': 'Цена раскрытия автора (⭐)',     'kind': 'int', 'default': '40'},
    {'key': 'anon_reveal_cost',         'label': 'Цена раскрытия собеседника (⭐)', 'kind': 'int', 'default': '40'},
    {'key': 'hide_authorship_cost',     'label': 'Цена скрытия авторства (⭐)',     'kind': 'int', 'default': '100'},
    {'key': 'bait_delay_minutes',       'label': 'Задержка байта (мин)',           'kind': 'int', 'default': '40'},
    {'key': 'record_reward_views',      'label': 'Награда за свой кружок (просм.)', 'kind': 'int', 'default': '1'},
    {'key': 'daily_upload_limit',       'label': 'Лимит загрузок в день',          'kind': 'int', 'default': '2'},
    {'key': 'bait_costs_view',          'label': 'Приманки списывают просмотр (1/0)', 'kind': 'int', 'default': '1'},
    {'key': 'view_packages',            'label': 'Пакеты просмотров',              'kind': 'pkg', 'default': '5:5,10:9,40:32,100:75,500:325'},
    {'key': 'author_packages',          'label': 'Пакеты авторов',                 'kind': 'pkg', 'default': '1:40,10:400,30:1200,75:3000'},
    {'key': 'upload_packages',          'label': 'Пакеты доп-загрузок',            'kind': 'pkg', 'default': '1:15,5:60,15:150'},
]

TEXT_SETTINGS = [
    {'key': 'txt_welcome',       'label': 'Приветствие',          'default': texts.get_welcome_text("{name}")},
    {'key': 'txt_op',            'label': 'Текст ОП',             'default': texts.get_op_text()},
    {'key': 'txt_no_circles',    'label': 'Нет новых кружков',    'default': texts.get_no_circles_text()},
    {'key': 'txt_out_of_views',  'label': 'Просмотры кончились',  'default': texts.get_out_of_views_text()},
    {'key': 'txt_record_prompt', 'label': 'Запись кружка',        'default': texts.get_record_prompt_text()},
    {'key': 'txt_banned',        'label': 'Бан',                  'default': texts.get_banned_text()},
    {'key': 'txt_rules',         'label': 'Правила',              'default': texts.get_rules_text()},
    {'key': 'txt_faq',           'label': 'FAQ',                  'default': texts.get_faq_text()},
]

_DEFAULTS = {s['key']: s['default'] for s in ECONOMY_SETTINGS}
_DEFAULTS.update({s['key']: s['default'] for s in TEXT_SETTINGS})


def default_for(key: str) -> str:
    return _DEFAULTS.get(key, '')


async def get_int(key: str) -> int:
    return await db.get_setting_int(key, int(_DEFAULTS.get(key, '0') or 0))


async def get_text(key: str) -> str:
    val = await db.get_setting(key)
    return val if val else _DEFAULTS.get(key, '')


async def get_moderation_channel_id() -> Optional[int]:
    """ID канала, куда дублируются кружки на модерацию.
    Берётся из админки (app_settings), фолбэк — config.ADMIN_CHANNEL_ID."""
    raw = await db.get_setting(MOD_CHANNEL_KEY)
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return getattr(config, 'ADMIN_CHANNEL_ID', None)


async def render_welcome(name: str) -> str:
    tmpl = await get_text('txt_welcome')
    return tmpl.replace("{name}", name or "друг")


def parse_packages(raw: str) -> List[Tuple[int, int]]:
    """'5:5,10:9' -> [(5,5),(10,9)]. Игнорирует битые пары."""
    out: List[Tuple[int, int]] = []
    for part in (raw or '').split(','):
        part = part.strip()
        if not part or ':' not in part:
            continue
        a, b = part.split(':', 1)
        try:
            count, stars = int(a), int(b)
            if count > 0 and stars > 0:
                out.append((count, stars))
        except ValueError:
            continue
    return out


async def get_view_packages() -> List[Tuple[int, int]]:
    raw = await db.get_setting('view_packages')
    pkgs = parse_packages(raw or _DEFAULTS['view_packages'])
    return pkgs or parse_packages(_DEFAULTS['view_packages'])


async def get_author_packages() -> List[Tuple[int, int]]:
    raw = await db.get_setting('author_packages')
    pkgs = parse_packages(raw or _DEFAULTS['author_packages'])
    return pkgs or parse_packages(_DEFAULTS['author_packages'])


async def get_upload_packages() -> List[Tuple[int, int]]:
    raw = await db.get_setting('upload_packages')
    pkgs = parse_packages(raw or _DEFAULTS['upload_packages'])
    return pkgs or parse_packages(_DEFAULTS['upload_packages'])


async def new_op_threshold() -> int:
    lo = await get_int('op_min_interval')
    hi = await get_int('op_max_interval')
    if hi < lo:
        lo, hi = hi, lo
    import random as _r
    return _r.randint(max(1, lo), max(1, hi))
