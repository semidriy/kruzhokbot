import random

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

from database.db_instance import db
from keyboards.inline_keyboards import get_main_reply_kb
from utils.texts import E


async def get_or_create(user_object: User) -> dict:
    return await db.get_or_create_user(
        user_id=user_object.id,
        username=user_object.username,
        first_name=user_object.first_name,
        is_premium=bool(user_object.is_premium),
    )


async def show_main_menu(message: Message, state: FSMContext, user_object: User,
                         text: str = None):
    """Показывает главное меню (reply-клавиатура) с актуальным балансом просмотров."""
    await state.clear()
    user = await get_or_create(user_object)
    views = user.get("views_balance", 0)

    if text is None:
        text = (
            f"{E.STARW} <b>Главное меню</b>\n\n"
            f"{E.EYE} Доступно просмотров: <b>{views}</b>\n"
            f"<i>Выбирай действие на клавиатуре ниже {E.NEXT}</i>"
        )

    await message.answer(text, reply_markup=get_main_reply_kb(views))


def new_op_threshold() -> int:
    """Случайный порог 7–10 просмотров до следующей ОП."""
    return random.randint(7, 10)
