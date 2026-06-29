"""
Анонимный чат: подбор собеседника по полу/возрасту, релей ТОЛЬКО текста,
антислив юзернеймов/контактов, раскрытие собеседника за звёзды, жалобы.
Этот роутер регистрируется ПОСЛЕДНИМ — релей ловит только сообщения тех,
кто сейчас в активной паре (проверка по БД).
"""
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.markdown import hlink

import config
from database.db_instance import db
from utils import texts
from utils import app_config as cfg
from utils.texts import E
from states.game_states import UserFlow
from keyboards.inline_keyboards import (
    BTN_ANON, get_main_reply_kb, get_anon_menu_kb, get_anon_setup_gender_kb,
    get_anon_search_reply_kb, get_anon_chat_reply_kb, get_anon_reveal_buy_kb,
    get_anon_after_chat_kb,
    ANON_CANCEL, ANON_NEXT, ANON_STOP, ANON_REVEAL, ANON_REPORT,
)

router = Router()


async def _restore_menu(bot: Bot, uid: int, text: str = None):
    u = await db.get_user(uid)
    await bot.send_message(
        uid, text or f"{E.STARW} Главное меню",
        reply_markup=get_main_reply_kb((u or {}).get('views_balance', 0)),
    )


async def _enter_chat(bot: Bot, uid: int):
    await bot.send_message(uid, texts.get_anon_matched(), reply_markup=get_anon_chat_reply_kb())


async def _start_search(bot: Bot, tg_user):
    uid = tg_user.id
    user = await db.get_user(uid)
    if not user or not user.get('anon_gender') or not user.get('anon_age'):
        return False
    partner = await db.anon_match_or_enqueue(uid, user['anon_gender'], user['anon_age'])
    if partner:
        await _enter_chat(bot, uid)
        await _enter_chat(bot, partner)
    else:
        await bot.send_message(uid, texts.get_anon_searching(), reply_markup=get_anon_search_reply_kb())
    return True


async def _remember_partners(uid: int, partner: int):
    """Запоминает последнего собеседника у обоих — для раскрытия после диалога."""
    try:
        await db.set_last_anon_partner(uid, partner)
        await db.set_last_anon_partner(partner, uid)
    except Exception:
        pass


async def _offer_contact(bot: Bot, uid: int):
    """Предлагает узнать контакт собеседника после завершения диалога."""
    try:
        await bot.send_message(
            uid, texts.get_anon_offer_contact(), reply_markup=get_anon_after_chat_kb()
        )
    except Exception:
        pass


async def _partner_contact(partner_id: int) -> str:
    u = await db.get_user(partner_id)
    if u and u.get('username'):
        return f"@{u['username']}"
    if u:
        return hlink(u.get('first_name') or "Собеседник", f"tg://user?id={partner_id}")
    return "неизвестно"



@router.message(F.text == BTN_ANON)
async def anon_entry(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if await db.anon_get_partner(message.from_user.id):
        await message.answer(f"{E.CHAT} Ты уже в диалоге. Используй кнопки внизу.",
                             reply_markup=get_anon_chat_reply_kb())
        return
    user = await db.get_user(message.from_user.id)
    if not user or not user.get('anon_gender') or not user.get('anon_age'):
        await state.set_state(UserFlow.anon_setup_gender)
        await message.answer(texts.get_anon_ask_gender(), reply_markup=get_anon_setup_gender_kb())
        return
    await message.answer(texts.get_anon_menu_text(user.get('anon_gender'), user.get('anon_age')),
                         reply_markup=get_anon_menu_kb())


@router.callback_query(F.data == "anon:profile")
async def anon_profile_cb(query: CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.anon_setup_gender)
    await query.answer()
    await query.message.answer(texts.get_anon_ask_gender(), reply_markup=get_anon_setup_gender_kb())


@router.callback_query(F.data.startswith("anonsetup:"), UserFlow.anon_setup_gender)
async def anon_setup_gender_cb(query: CallbackQuery, state: FSMContext):
    gender = query.data.split(":")[1]
    await state.update_data(anon_gender=gender)
    await state.set_state(UserFlow.anon_setup_age)
    await query.answer()
    try:
        await query.message.edit_text(texts.get_anon_ask_age())
    except Exception:
        await query.message.answer(texts.get_anon_ask_age())


@router.message(UserFlow.anon_setup_age, F.text)
async def anon_setup_age_msg(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw.isdigit() or not (10 <= int(raw) <= 99):
        await message.answer(f"{E.WARN} Введи корректный возраст числом (10–99).")
        return
    data = await state.get_data()
    gender = data.get('anon_gender', 'male')
    await db.set_anon_profile(message.from_user.id, gender, int(raw))
    await state.clear()
    await message.answer(texts.get_anon_menu_text(gender, int(raw)), reply_markup=get_anon_menu_kb())


@router.callback_query(F.data == "anon:find")
async def anon_find_cb(query: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await query.answer()
    ok = await _start_search(bot, query.from_user)
    if not ok:
        await state.set_state(UserFlow.anon_setup_gender)
        await query.message.answer(texts.get_anon_ask_gender(), reply_markup=get_anon_setup_gender_kb())



@router.message(F.text == ANON_CANCEL)
async def anon_cancel(message: Message, bot: Bot):
    await db.anon_dequeue(message.from_user.id)
    await _restore_menu(bot, message.from_user.id, f"{E.CHECK} Поиск отменён.")


@router.message(F.text == ANON_STOP)
async def anon_stop(message: Message, bot: Bot):
    uid = message.from_user.id
    partner = await db.anon_end_pair(uid)
    await db.anon_dequeue(uid)
    await _restore_menu(bot, uid, f"{E.CHECK} Диалог завершён.")
    if partner:
        await _remember_partners(uid, partner)
        await _offer_contact(bot, uid)
        await _restore_menu(bot, partner, texts.get_anon_partner_left())
        await _offer_contact(bot, partner)


@router.message(F.text == ANON_NEXT)
async def anon_next(message: Message, bot: Bot):
    uid = message.from_user.id
    partner = await db.anon_end_pair(uid)
    if partner:
        await _remember_partners(uid, partner)
        await _restore_menu(bot, partner, texts.get_anon_partner_left())
        await _offer_contact(bot, partner)
    await _start_search(bot, message.from_user)


@router.message(F.text == ANON_REVEAL)
async def anon_reveal(message: Message, bot: Bot):
    partner = await db.anon_get_partner(message.from_user.id)
    if not partner:
        await message.answer(f"{E.WARN} Ты сейчас не в диалоге.")
        return
    bal = (await db.get_user(message.from_user.id)).get('author_reveal_balance', 0)
    if bal <= 0:
        cost = await cfg.get_int('anon_reveal_cost')
        await message.answer(texts.get_anon_need_balance(cost), reply_markup=get_anon_reveal_buy_kb())
        return
    await db.add_author_reveal_balance(message.from_user.id, -1)
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET author_views_count = author_views_count + 1 WHERE user_id = $1",
                           message.from_user.id)
    contact = await _partner_contact(partner)
    await message.answer(texts.get_anon_revealed(contact))


@router.callback_query(F.data == "anon:reveal_last")
async def anon_reveal_last_cb(query: CallbackQuery, bot: Bot):
    uid = query.from_user.id
    partner = await db.get_last_anon_partner(uid)
    if not partner:
        await query.answer("Нет недавнего собеседника.", show_alert=True)
        return
    bal = (await db.get_user(uid) or {}).get('author_reveal_balance', 0)
    if bal <= 0:
        cost = await cfg.get_int('anon_reveal_cost')
        await query.message.answer(texts.get_anon_need_balance(cost), reply_markup=get_anon_reveal_buy_kb())
        await query.answer()
        return
    await db.add_author_reveal_balance(uid, -1)
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET author_views_count = author_views_count + 1 WHERE user_id = $1", uid)
    contact = await _partner_contact(partner)
    await query.message.answer(texts.get_anon_revealed(contact))
    await query.answer()


@router.callback_query(F.data == "anon:after_close")
async def anon_after_close_cb(query: CallbackQuery):
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.answer()


@router.message(F.text == ANON_REPORT)
async def anon_report(message: Message, bot: Bot):
    partner = await db.anon_get_partner(message.from_user.id)
    if not partner:
        await message.answer(f"{E.WARN} Ты сейчас не в диалоге.")
        return
    rid = await db.add_report(reporter_id=message.from_user.id, target_type='anon_user',
                              target_user_id=partner, reason='Жалоба в анонимном чате')
    if config.ADMIN_CHANNEL_ID:
        try:
            await bot.send_message(
                config.ADMIN_CHANNEL_ID,
                f"🚩 <b>Жалоба #{rid}</b> (анон-чат)\nНа пользователя: {partner}\nОт: {message.from_user.id}",
            )
        except Exception:
            pass
    await message.answer(texts.get_report_sent_text())



async def _in_chat(message: Message) -> bool:
    try:
        return await db.anon_get_partner(message.from_user.id) is not None
    except Exception:
        return False


@router.message(_in_chat, F.text)
async def anon_relay_text(message: Message, bot: Bot):
    partner = await db.anon_get_partner(message.from_user.id)
    if not partner:
        return
    if texts.contains_contact(message.text):
        await message.answer(texts.get_anon_leak_blocked())
        return
    try:
        await bot.send_message(partner, message.text)
    except Exception as e:
        logging.warning(f"anon relay failed to {partner}: {e}")
        await message.answer(f"{E.WARN} Не удалось доставить сообщение.")


@router.message(_in_chat)
async def anon_relay_block_media(message: Message):
    await message.answer(texts.get_anon_only_text())
