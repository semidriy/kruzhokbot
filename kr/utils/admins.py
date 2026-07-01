"""
Список администраторов бота = постоянные супер-админы из .env (config.ADMIN_IDS)
+ динамические админы, выданные через админ-панель (таблица bot_admins).

Динамические ID кешируются в памяти и обновляются при добавлении/удалении,
чтобы фильтр IsAdmin не ходил в БД на каждое сообщение.
"""
import config
from database.db_instance import db

# ID, выданные через панель (загружаются из БД при старте бота)
_dynamic_admins: set[int] = set()


async def load_admins() -> None:
    """Загрузить динамических админов из БД в кеш (вызывается на старте бота)."""
    global _dynamic_admins
    rows = await db.get_bot_admins()
    _dynamic_admins = {row['user_id'] for row in rows}


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS or user_id in _dynamic_admins


def is_super_admin(user_id: int) -> bool:
    """Постоянный админ из .env — его нельзя снять через панель."""
    return user_id in config.ADMIN_IDS


def cache_add_admin(user_id: int) -> None:
    _dynamic_admins.add(user_id)


def cache_remove_admin(user_id: int) -> None:
    _dynamic_admins.discard(user_id)


def dynamic_admin_ids() -> set[int]:
    return set(_dynamic_admins)


def all_admin_ids() -> set[int]:
    return set(config.ADMIN_IDS) | _dynamic_admins
