import asyncio
import logging
import random
import re
import time
import uuid

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, ChatJoinRequest, LabeledPrice, User,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hlink
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.db_instance import db
from keyboards.inline_keyboards import (
    get_main_reply_kb, get_start_inline_kb, get_subscription_channels_kb,
    get_circle_kb, get_feed_settings_kb, get_profile_kb, get_referral_kb,
    get_buy_views_kb, get_buy_authors_kb, get_reveal_buy_kb, get_top_circles_kb,
    get_record_gender_kb, get_my_circles_kb, get_buy_uploads_kb,
    get_start_gender_kb, get_start_feed_kb, get_circle_moderation_kb,
    BTN_WATCH, BTN_FEED, BTN_PROFILE, BTN_INVITE, BTN_TASKS, BTN_ANON,
    _ib,
)
from states.game_states import UserFlow
from utils import texts
from utils import app_config as cfg
from utils.texts import E, mask_name
from handlers.common_actions import get_or_create
from services.op_aggregator import get_op_channels_single, check_op_stage
from urllib.parse import urlparse, parse_qs

router = Router()

_MENU_EXACT = frozenset({BTN_FEED, BTN_PROFILE, BTN_INVITE, BTN_TASKS, BTN_ANON})

_scheduler: AsyncIOScheduler = None


def set_scheduler(scheduler: AsyncIOScheduler):
    global _scheduler
    _scheduler = scheduler



def _compute_target_key(item: dict) -> str:
    chat_id = item.get('chat_id')
    if chat_id:
        return f"chat:{chat_id}"
    url = item.get('url') or item.get('link')
    if not url:
        return f"item:{hash(str(item))}"
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or '').lower()
        path = (parsed.path or '').strip('/')
        if host in ('t.me', 'telegram.me'):
            username = (path.split('/')[0] if path else '').lower()
            if username:
                return f"tme:{username}"
        if 'subgram.org' in host:
            qs = parse_qs(parsed.query or '')
            bot_param = (qs.get('bot') or [None])[0]
            if bot_param:
                return f"tme:{bot_param.lower()}"
        return f"url:{host}/{path.lower()}"
    except Exception:
        return f"url:{url.lower()}"


def _dedup(channels: list) -> list:
    seen, out = set(), []
    for ch in channels:
        k = _compute_target_key(ch)
        if k in seen:
            continue
        seen.add(k)
        out.append(ch)
    return out


async def _resolve_op_channels(tg_user) -> list:
    """Собирает одноэтапную ОП с учётом вайтлиста и дедупликации."""
    channels = await get_op_channels_single(tg_user, db=db)
    if await db.is_user_in_whitelist(tg_user.id):
        excl = set(await db.get_whitelist_exclusions(tg_user.id)) | set(await db.get_whitelist_global_exclusions())
        if excl:
            channels = [c for c in channels if c.get('id') not in excl]
    return _dedup(channels)


async def _send_circle(bot: Bot, chat_id: int, user_id: int, circle: dict, balance: int = None):
    """Отправляет подпись + кружок. При balance обновляет счётчик просмотров на reply-клавиатуре."""
    if circle.get('is_bait'):
        author_display = circle.get('fake_author_name') or "Аноним"
    else:
        owner = await db.get_user(circle.get('owner_id')) if circle.get('owner_id') else None
        author_display = (owner or {}).get('first_name') or "Аноним"
    masked = mask_name(author_display)

    caption_kb = get_main_reply_kb(balance) if balance is not None else None
    await bot.send_message(chat_id, texts.get_circle_caption(masked), reply_markup=caption_kb)
    revealed = await db.has_revealed_author(user_id, circle['id'])
    try:
        await bot.send_video_note(
            chat_id, video_note=circle['file_id'],
            reply_markup=await get_circle_kb(circle, revealed=revealed),
        )
    except Exception as e:
        logging.error(f"send_video_note failed circle={circle['id']}: {e}")
        await bot.send_message(chat_id, f"{E.WARN} Этот кружок недоступен, пропускаем.")


async def serve_next_circle(bot: Bot, tg_user, state: FSMContext):
    """
    Центральная логика выдачи кружка:
    приманки → пост-приманочная ОП → лента + ОП каждые 7–10 просмотров.
    """
    user_id = tg_user.id
    await db.update_user_activity(user_id)
    user = await get_or_create(tg_user)

    if user.get('is_banned'):
        await bot.send_message(user_id, await cfg.get_text('txt_banned'))
        return

    if not user.get('onboarded'):
        await bot.send_message(user_id, texts.get_ask_gender_text(), reply_markup=get_start_gender_kb())
        return

    try:
        from utils.ad_shows import send_show_d_if_needed
        await send_show_d_if_needed(bot, user_id)
    except Exception:
        pass

    feed_gender = user.get('feed_gender', 'any')
    bait_count = await db.count_active_bait(feed_gender)
    in_bait = (user.get('bait_index', 0) < bait_count)

    need_op = False
    if not in_bait:
        if not user.get('has_passed_first_op'):
            need_op = True
        elif user.get('views_since_op', 0) >= user.get('next_op_threshold', 7):
            need_op = True

    if need_op:
        channels = await _resolve_op_channels(tg_user)
        if channels:
            already = await check_op_stage(
                channels_to_check=channels, user_id=user_id,
                is_premium=bool(tg_user.is_premium),
                lang=tg_user.language_code or 'ru', db=db, bot=bot,
            )
            if not already:
                await state.set_state(UserFlow.waiting_for_op)
                await state.update_data(op_channels=channels)
                await db.increment_channels_shown(
                    [c['id'] for c in channels if c.get('source_service') == 'admin' and c.get('id')]
                )
                op_text = (texts.get_op_resub_text() if user.get('has_passed_first_op')
                           else await cfg.get_text('txt_op'))
                await bot.send_message(
                    user_id, op_text,
                    reply_markup=get_subscription_channels_kb(channels, "check_op_sub"),
                )
                return
        await db.set_first_op_passed(user_id)
        await db.mark_op_as_started(user_id)
        await db.set_op_passed(user_id)
        await db.reset_op_counter(user_id, await cfg.new_op_threshold())

    if in_bait:
        circle = await db.get_next_bait_circle(user.get('bait_index', 0), feed_gender)
        if circle:
            balance = await db.get_views_balance(user_id)
            if await cfg.get_int('bait_costs_view'):
                if balance <= 0:
                    await bot.send_message(
                        user_id, await cfg.get_text('txt_out_of_views'),
                        reply_markup=await get_buy_views_kb(),
                    )
                    return
                balance = await db.add_views_balance(user_id, -1)
            await db.mark_circle_viewed(user_id, circle['id'])
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE users SET bait_index = bait_index + 1 WHERE user_id = $1", user_id)
            await _send_circle(bot, user_id, user_id, circle, balance)
            return

    balance = await db.get_views_balance(user_id)
    if balance <= 0:
        await bot.send_message(
            user_id, await cfg.get_text('txt_out_of_views'),
            reply_markup=await get_buy_views_kb(),
        )
        return

    circle = await db.get_random_unseen_circle(user_id, user.get('feed_gender', 'any'))
    if not circle:
        await bot.send_message(user_id, await cfg.get_text('txt_no_circles'))
        return

    new_balance = await db.add_views_balance(user_id, -1)
    await db.increment_op_counter(user_id)
    await db.mark_circle_viewed(user_id, circle['id'])
    await _send_circle(bot, user_id, user_id, circle, new_balance)



@router.chat_join_request()
async def handle_join_request(event: ChatJoinRequest, state: FSMContext):
    await db.log_join_request(user_id=event.from_user.id, chat_id=event.chat.id)


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext, command: CommandObject, bot: Bot):
    await state.clear()
    try:
        partner = await db.anon_end_pair(message.from_user.id)
        await db.anon_dequeue(message.from_user.id)
        if partner:
            from keyboards.inline_keyboards import get_main_reply_kb as _mrk
            pu = await db.get_user(partner)
            await bot.send_message(partner, texts.get_anon_partner_left(),
                                   reply_markup=_mrk((pu or {}).get('views_balance', 0)))
    except Exception:
        pass
    referrer_id = None
    ad_link_name = None

    if command and command.args:
        args = command.args
        if args.startswith('adv_'):
            ad_link_name = args[4:]
        elif args.startswith('ref_'):
            try:
                referrer_id = int(args.split('_')[1])
                if referrer_id == message.from_user.id:
                    referrer_id = None
            except (ValueError, IndexError):
                referrer_id = None

    existed = await db.get_user(message.from_user.id)
    user = await db.get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        is_premium=bool(message.from_user.is_premium),
        referrer_id=referrer_id,
        ad_link_name=ad_link_name,
    )

    if user.get('is_banned'):
        await message.answer(await cfg.get_text('txt_banned'))
        return

    if not existed:
        free = await cfg.get_int('free_initial_views')
        cur = user.get('views_balance', 0)
        if free != cur:
            await db.add_views_balance(message.from_user.id, free - cur)
            user['views_balance'] = free

    if not existed and referrer_id:
        try:
            ref_views = await cfg.get_int('ref_reward_views')
            ref_author = await cfg.get_int('ref_reward_author_views')
            await db.add_views_balance(referrer_id, ref_views)
            await db.add_author_reveal_balance(referrer_id, ref_author)
            await db.increment_referrals(referrer_id)
            await bot.send_message(
                referrer_id,
                f"{E.GIFT} <b>Новый друг по твоей ссылке!</b>\n"
                f"{E.PLAY} +{ref_views} просмотров кружков\n"
                f"{E.EYE} +{ref_author} просмотра авторов",
            )
        except Exception as e:
            logging.warning(f"referral reward failed: {e}")

    try:
        asyncio.create_task(db.schedule_shows_n_for_user(message.from_user.id))
    except Exception:
        pass

    if _scheduler:
        try:
            from scheduler.jobs import clear_user_show_jobs, schedule_shows_for_user
            await clear_user_show_jobs(_scheduler, message.from_user.id)
            await schedule_shows_for_user(bot, _scheduler, message.from_user.id)
        except Exception as e:
            logging.error(f"schedule shows failed: {e}")

    if not user.get('onboarded'):
        await message.answer(texts.get_ask_gender_text(), reply_markup=get_start_gender_kb())
        return

    await _finish_start(bot, message.chat.id, message.from_user.first_name)


async def _finish_start(bot: Bot, chat_id: int, first_name: str):
    """Показывает приветку + приветствие + кнопку старта (после онбординга)."""
    greetings = [g for g in await db.get_all_greetings() if g.get('is_active', True)]
    if greetings:
        from utils.message_sender import send_stored_message
        g = random.choice(greetings)
        try:
            ok = await send_stored_message(bot, chat_id, g['from_chat_id'], g['message_id'],
                                           msg_json_raw=g.get('message_json'), label=f"greeting#{g['id']}")
            if ok:
                await db.increment_greeting_count(g['id'])
            await asyncio.sleep(0.5)
        except Exception:
            pass

    u = await db.get_user(chat_id)
    views = (u or {}).get('views_balance', 0)
    await bot.send_message(chat_id, await cfg.render_welcome(first_name),
                           reply_markup=get_main_reply_kb(views))
    await bot.send_message(chat_id, f"{E.NEXT} Нажми «Смотреть кружки», чтобы начать {E.EYE}",
                           reply_markup=get_start_inline_kb())


@router.callback_query(F.data.startswith("start:gender:"))
async def start_gender_cb(query: CallbackQuery):
    gender = query.data.split(":")[-1]
    if gender not in ("male", "female"):
        await query.answer()
        return
    await db.set_user_gender(query.from_user.id, gender)
    try:
        await query.message.edit_text(texts.get_ask_feed_text(), reply_markup=get_start_feed_kb())
    except Exception:
        await query.message.answer(texts.get_ask_feed_text(), reply_markup=get_start_feed_kb())
    await query.answer()


@router.callback_query(F.data.startswith("start:feed:"))
async def start_feed_cb(query: CallbackQuery):
    g = query.data.split(":")[-1]
    if g not in ("male", "female", "any"):
        await query.answer()
        return
    await db.set_feed_gender(query.from_user.id, g)
    await db.set_user_onboarded(query.from_user.id)
    label = {"male": "мужские", "female": "женские", "any": "любые"}[g]
    try:
        await query.message.edit_text(f"{E.CHECK} Готово! Лента: <b>{label}</b>.")
    except Exception:
        pass
    await query.answer("Сохранено")
    await _finish_start(query.bot, query.from_user.id, query.from_user.first_name)



@router.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.answer(await cfg.get_text('txt_rules'))


@router.message(Command("faq"))
async def cmd_faq(message: Message):
    await message.answer(await cfg.get_text('txt_faq'))


@router.callback_query(F.data == "info:rules")
async def info_rules_cb(query: CallbackQuery):
    await query.answer()
    await query.message.answer(await cfg.get_text('txt_rules'))


@router.callback_query(F.data == "info:faq")
async def info_faq_cb(query: CallbackQuery):
    await query.answer()
    await query.message.answer(await cfg.get_text('txt_faq'))



@router.message(F.text.startswith(BTN_WATCH))
async def watch_circles_btn(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await serve_next_circle(bot, message.from_user, state)


@router.callback_query(F.data == "circle:next")
async def circle_next_cb(query: CallbackQuery, state: FSMContext, bot: Bot):
    await query.answer()
    cur = await state.get_state()
    if cur == UserFlow.waiting_for_op:
        return
    await serve_next_circle(bot, query.from_user, state)


@router.callback_query(F.data == "check_op_sub", UserFlow.waiting_for_op)
async def check_op_sub_cb(query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    channels = data.get('op_channels', [])
    await query.answer("Проверяю подписку...")
    ok = await check_op_stage(
        channels_to_check=channels, user_id=query.from_user.id,
        is_premium=bool(query.from_user.is_premium),
        lang=query.from_user.language_code or 'ru', db=db, bot=bot,
    )
    if not ok:
        await query.answer(f"❗ Ты подписался не на все каналы", show_alert=True)
        return
    await db.increment_channels_passed(
        [c['id'] for c in channels if c.get('source_service') == 'admin' and c.get('id')]
    )
    await db.set_first_op_passed(query.from_user.id)
    await db.mark_op_as_started(query.from_user.id)
    await db.set_op_passed(query.from_user.id)
    await db.reset_op_counter(query.from_user.id, await cfg.new_op_threshold())
    await state.clear()
    try:
        await query.message.delete()
    except Exception:
        pass
    await serve_next_circle(bot, query.from_user, state)


@router.callback_query(F.data.startswith("circle:like:"))
async def circle_like_cb(query: CallbackQuery):
    await _react(query, 'like')


@router.callback_query(F.data.startswith("circle:dislike:"))
async def circle_dislike_cb(query: CallbackQuery):
    await _react(query, 'dislike')


async def _react(query: CallbackQuery, reaction: str):
    cid = int(query.data.split(":")[2])
    await db.set_circle_reaction(query.from_user.id, cid, reaction)
    circle = await db.get_circle(cid)
    if not circle:
        await query.answer()
        return
    revealed = await db.has_revealed_author(query.from_user.id, cid)
    try:
        await query.message.edit_reply_markup(reply_markup=await get_circle_kb(circle, revealed=revealed))
    except Exception:
        pass
    await query.answer("❤️" if reaction == 'like' else "👎")


@router.callback_query(F.data.startswith("circle:reveal:"))
async def circle_reveal_cb(query: CallbackQuery, bot: Bot):
    cid = int(query.data.split(":")[2])
    circle = await db.get_circle(cid)
    if not circle:
        await query.answer("Кружок не найден.", show_alert=True)
        return

    if not circle.get('is_bait') and circle.get('owner_id'):
        owner = await db.get_user(circle['owner_id'])
        if owner and owner.get('hide_authorship'):
            await query.answer()
            await bot.send_message(query.from_user.id, f"{E.LOCK} <b>Автор скрыл свой профиль.</b>")
            return

    already = await db.has_revealed_author(query.from_user.id, cid)
    if not already:
        bal = (await db.get_user(query.from_user.id)).get('author_reveal_balance', 0)
        if bal <= 0:
            cost = await cfg.get_int('author_reveal_cost')
            await query.answer()
            await bot.send_message(
                query.from_user.id, texts.get_need_author_balance_text(cost),
                reply_markup=get_reveal_buy_kb(cid),
            )
            return
        await db.add_author_reveal_balance(query.from_user.id, -1)
        await db.add_author_reveal(query.from_user.id, cid)

    contact = await _author_contact(circle)
    await query.answer()
    await bot.send_message(query.from_user.id, texts.get_author_revealed_text(contact))
    try:
        await query.message.edit_reply_markup(reply_markup=await get_circle_kb(circle, revealed=True))
    except Exception:
        pass


async def _author_contact(circle: dict) -> str:
    if circle.get('is_bait'):
        if circle.get('fake_author_username'):
            uname = circle['fake_author_username'].lstrip('@')
            return f"@{uname}"
        if circle.get('fake_author_url'):
            return hlink(circle.get('fake_author_name') or "Автор", circle['fake_author_url'])
        return circle.get('fake_author_name') or "Аноним"
    owner = await db.get_user(circle.get('owner_id')) if circle.get('owner_id') else None
    if owner and owner.get('username'):
        return f"@{owner['username']}"
    if owner:
        return hlink(owner.get('first_name') or "Автор", f"tg://user?id={owner['user_id']}")
    return "Аноним"


@router.callback_query(F.data.startswith("circle:report:"))
async def circle_report_cb(query: CallbackQuery, state: FSMContext):
    cid = int(query.data.split(":")[2])
    await state.set_state(UserFlow.reporting_circle)
    await state.update_data(report_circle_id=cid)
    await query.answer()
    await query.message.answer(texts.get_report_prompt())


@router.message(UserFlow.reporting_circle, F.text, ~F.text.startswith(BTN_WATCH), ~F.text.in_(_MENU_EXACT))
async def process_report(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    cid = data.get('report_circle_id')
    await state.clear()
    circle = await db.get_circle(cid) if cid else None
    target_user = circle.get('owner_id') if circle else None
    rid = await db.add_report(
        reporter_id=message.from_user.id, target_type='circle',
        target_circle_id=cid, target_user_id=target_user, reason=message.text[:500],
    )
    if config.ADMIN_CHANNEL_ID:
        try:
            await bot.send_message(
                config.ADMIN_CHANNEL_ID,
                f"🚩 <b>Новая жалоба #{rid}</b>\n"
                f"На кружок ID {cid} (автор {target_user})\n"
                f"От: {message.from_user.id}\n"
                f"Причина: {message.text[:300]}",
            )
        except Exception:
            pass
    await message.answer(texts.get_report_sent_text())
    await serve_next_circle(bot, message.from_user, state)



@router.message(F.text == BTN_FEED)
async def feed_btn(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    g = (user or {}).get('feed_gender', 'any')
    await message.answer(texts.get_feed_settings_text(g), reply_markup=get_feed_settings_kb(g))


@router.callback_query(F.data.startswith("feed:set:"))
async def feed_set_cb(query: CallbackQuery):
    g = query.data.split(":")[2]
    await db.set_feed_gender(query.from_user.id, g)
    await query.answer("Готово")
    try:
        await query.message.edit_text(texts.get_feed_settings_text(g), reply_markup=get_feed_settings_kb(g))
    except Exception:
        pass


@router.callback_query(F.data == "feed:close")
async def feed_close_cb(query: CallbackQuery):
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass



@router.message(F.text == BTN_PROFILE)
async def profile_btn(message: Message, state: FSMContext):
    await state.clear()
    await _show_profile(message, message.from_user)


async def _build_profile(tg_user):
    """Текст и клавиатура экрана профиля."""
    user = await get_or_create(tg_user)
    text = texts.get_profile_text(
        name=tg_user.first_name, username=tg_user.username,
        circle_views=user.get('circle_views_count', 0),
        author_views=user.get('author_views_count', 0),
        referrals=user.get('referrals_count', 0),
        views_balance=user.get('views_balance', 0),
        author_balance=user.get('author_reveal_balance', 0),
    )
    return text, await get_profile_kb(user.get('hide_authorship', False))


async def _show_profile(message: Message, tg_user):
    text, kb = await _build_profile(tg_user)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "profile:open")
async def profile_open_cb(query: CallbackQuery):
    await query.answer()
    text, kb = await _build_profile(query.from_user)
    try:
        await query.message.edit_text(text, reply_markup=kb)
    except Exception:
        await query.message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "profile:hide_toggle")
async def profile_hide_toggle_cb(query: CallbackQuery, bot: Bot):
    cur = await db.get_hide_authorship(query.from_user.id)
    if cur:
        await db.set_hide_authorship(query.from_user.id, False)
        await query.answer("Авторство снова открыто", show_alert=True)
        try:
            await query.message.edit_reply_markup(reply_markup=await get_profile_kb(False))
        except Exception:
            pass
        return
    cost = await cfg.get_int('hide_authorship_cost')
    await query.answer()
    await _send_invoice(bot, query, kind="hide", count=1, stars=cost,
                        title="Скрытие авторства")


@router.callback_query(F.data == "profile:best")
async def profile_best_cb(query: CallbackQuery, bot: Bot):
    await query.answer()
    circle = await db.get_best_circle(query.from_user.id)
    if not circle:
        await query.message.answer(f"{E.SCOPE} У тебя пока нет загруженных кружков.")
        return
    await bot.send_message(query.from_user.id,
                           f"{E.FIRE} <b>Твой лучший кружок</b>\n{E.HEART} {circle['likes']} · {E.EYE} {circle['views']}")
    try:
        await bot.send_video_note(query.from_user.id, video_note=circle['file_id'])
    except Exception:
        pass


@router.callback_query(F.data == "profile:top")
async def profile_top_cb(query: CallbackQuery):
    await query.answer()
    tops = await db.get_top_circles(10)
    if not tops:
        await query.message.answer(f"{E.SCOPE} Топ пока пуст.")
        return
    lines = [f"{E.CROWN} <b>Топ кружков</b>\n"]
    for i, c in enumerate(tops, 1):
        name = c.get('fake_author_name') or c.get('owner_first_name') or "Аноним"
        masked = mask_name(name)
        lines.append(f"{i}. <b>{masked}</b> — {E.HEART} {c['likes']} · {E.EYE} {c['views']}")
    await query.message.answer("\n".join(lines), reply_markup=get_top_circles_kb())



async def _can_upload(user_id: int) -> bool:
    """True, если есть бесплатный дневной слот или платный доп-слот."""
    limit = await cfg.get_int('daily_upload_limit')
    used = await db.count_uploads_today(user_id)
    if used < limit:
        return True
    user = await db.get_user(user_id)
    return (user or {}).get('extra_upload_credits', 0) > 0


@router.callback_query(F.data == "circle:record")
async def circle_record_cb(query: CallbackQuery, state: FSMContext):
    await query.answer()
    user = await db.get_user(query.from_user.id)
    if user and user.get('is_banned'):
        await query.message.answer(await cfg.get_text('txt_banned'))
        return
    if not await _can_upload(query.from_user.id):
        limit = await cfg.get_int('daily_upload_limit')
        credits = (user or {}).get('extra_upload_credits', 0)
        await query.message.answer(texts.get_upload_limit_text(limit, credits),
                                   reply_markup=await get_buy_uploads_kb())
        return
    await state.set_state(UserFlow.recording_circle)
    await query.message.answer(await cfg.get_text('txt_record_prompt'))


async def _post_circle_to_moderation(bot: Bot, circle_id: int, file_id: str,
                                     author: User, gender: str):
    """Дублирует свежий кружок в канал модерации с кнопками удаления из ленты."""
    channel_id = await cfg.get_moderation_channel_id()
    if not channel_id:
        return
    uname = f"@{author.username}" if author.username else "—"
    g = {'male': 'М', 'female': 'Ж', 'any': 'любой'}.get(gender, 'любой')
    try:
        await bot.send_message(
            channel_id,
            f"🆕 <b>Новый кружок #{circle_id}</b>\n"
            f"👤 Автор: {author.full_name} ({uname}, id <code>{author.id}</code>)\n"
            f"⚧ Пол ленты: {g}",
        )
        await bot.send_video_note(
            channel_id, video_note=file_id,
            reply_markup=get_circle_moderation_kb(circle_id),
        )
    except Exception as e:
        logging.error(f"post circle #{circle_id} to moderation channel failed: {e}")


@router.message(UserFlow.recording_circle, F.video_note)
async def record_receive_video(message: Message, state: FSMContext, bot: Bot):
    uid = message.from_user.id
    file_id = message.video_note.file_id
    await state.clear()
    user = await db.get_user(uid)
    gender = (user or {}).get('gender') or 'any'

    limit = await cfg.get_int('daily_upload_limit')
    used = await db.count_uploads_today(uid)
    paid = False
    if used >= limit:
        if not await db.use_extra_upload_credit(uid):
            credits = (user or {}).get('extra_upload_credits', 0)
            await message.answer(texts.get_upload_limit_text(limit, credits),
                                 reply_markup=await get_buy_uploads_kb())
            return
        paid = True

    cid = await db.add_circle(owner_id=uid, file_id=file_id, is_bait=False, gender=gender)
    reward = 0
    if not paid:
        await db.register_upload(uid)
        reward = await cfg.get_int('record_reward_views')
        if reward:
            await db.add_views_balance(uid, reward)
    await message.answer(texts.get_circle_published_text(reward, paid=paid))
    if reward:
        nb = (await db.get_user(uid) or {}).get('views_balance', 0)
        await message.answer(
            f"{E.PLAY} Баланс просмотров обновлён: <b>{nb}</b>",
            reply_markup=get_main_reply_kb(nb),
        )
    await _post_circle_to_moderation(bot, cid, file_id, message.from_user, gender)


@router.message(UserFlow.recording_circle, ~F.text.startswith(BTN_WATCH), ~F.text.in_(_MENU_EXACT))
async def record_not_a_video(message: Message):
    await message.answer(texts.get_record_need_video_note_text())


@router.callback_query(F.data == "mycircles:open")
async def my_circles_cb(query: CallbackQuery):
    await query.answer()
    circles = await db.get_own_circles(query.from_user.id)
    if not circles:
        await query.message.answer(texts.get_no_own_circles_text(),
                                   reply_markup=get_my_circles_kb([]))
        return
    try:
        await query.message.edit_text(texts.get_my_circles_text(len(circles)),
                                      reply_markup=get_my_circles_kb(circles))
    except Exception:
        await query.message.answer(texts.get_my_circles_text(len(circles)),
                                   reply_markup=get_my_circles_kb(circles))


@router.callback_query(F.data.startswith("mycircles:del:"))
async def my_circles_delete_cb(query: CallbackQuery):
    cid = int(query.data.split(":")[2])
    ok = await db.delete_own_circle(cid, query.from_user.id)
    await query.answer(texts.strip_html(texts.get_circle_deleted_text()) if ok else "Не получилось удалить.",
                       show_alert=not ok)
    circles = await db.get_own_circles(query.from_user.id)
    new_text = texts.get_my_circles_text(len(circles)) if circles else texts.get_no_own_circles_text()
    try:
        await query.message.edit_text(new_text, reply_markup=get_my_circles_kb(circles))
    except Exception:
        pass


@router.callback_query(F.data == "noop")
async def noop_cb(query: CallbackQuery):
    await query.answer()



@router.message(F.text == BTN_INVITE)
async def invite_btn(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await _show_referral(message, message.from_user, bot)


@router.callback_query(F.data == "menu:referrals")
async def referrals_cb(query: CallbackQuery, bot: Bot):
    await query.answer()
    await _show_referral(query.message, query.from_user, bot)


async def _show_referral(message: Message, tg_user, bot: Bot):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{tg_user.id}"
    user = await get_or_create(tg_user)
    text = texts.get_referral_text(
        ref_link,
        referrals=user.get('referrals_count', 0),
        views_balance=user.get('views_balance', 0),
        ref_views=await cfg.get_int('ref_reward_views'),
        ref_author_views=await cfg.get_int('ref_reward_author_views'),
    )
    await message.answer(text, reply_markup=await get_referral_kb(ref_link, texts.get_share_text(ref_link)))



@router.message(F.text == BTN_TASKS)
async def tasks_btn(message: Message, state: FSMContext):
    await state.clear()
    tasks = await db.get_active_admin_tasks()
    done = set(await db.get_completed_tasks_by_provider(message.from_user.id, 'admin'))
    builder = InlineKeyboardBuilder()
    available = [t for t in tasks if str(t['id']) not in done]
    if not available:
        await message.answer(f"{E.SCOPE} Заданий пока нет. Загляни позже!")
        return
    for t in available[:10]:
        builder.row(_ib(f"{t['name']} (+{t['reward_attempts']} просм.)", icon_id="5361986358015463601",
                        style="primary", url=t['url']))
        builder.row(_ib("Проверить", icon_id="5429501538806548545", style="success",
                        callback_data=f"task:check:{t['id']}"))
    await message.answer(f"{E.STARW} <b>Задания</b>\n<i>Выполни и получи бонусные просмотры!</i>",
                         reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("task:check:"))
async def task_check_cb(query: CallbackQuery, bot: Bot):
    task_id = int(query.data.split(":")[2])
    done = set(await db.get_completed_tasks_by_provider(query.from_user.id, 'admin'))
    if str(task_id) in done:
        await query.answer("Уже выполнено.", show_alert=True)
        return
    task = await db.get_admin_task_by_id(task_id)
    if not task:
        await query.answer("Задание не найдено.", show_alert=True)
        return
    ok = True
    ct = task.get('check_type')
    if ct in ('join_request', 'membership'):
        try:
            if await db.check_join_request(query.from_user.id, task['chat_id']):
                ok = True
            else:
                m = await bot.get_chat_member(task['chat_id'], query.from_user.id)
                ok = m.status in ('member', 'administrator', 'creator')
        except Exception:
            ok = False
    if not ok:
        await query.answer("❌ Задание ещё не выполнено.", show_alert=True)
        return
    await db.add_completed_task(query.from_user.id, 'admin', str(task_id))
    reward = task.get('reward_attempts', 1)
    await db.add_views_balance(query.from_user.id, reward)
    await query.answer(f"✅ +{reward} просмотров!", show_alert=True)



@router.callback_query(F.data == "buy:views")
async def buy_views_menu(query: CallbackQuery):
    await query.answer()
    bal = (await db.get_user(query.from_user.id)).get('views_balance', 0)
    try:
        await query.message.edit_text(texts.get_buy_views_text(bal), reply_markup=await get_buy_views_kb())
    except Exception:
        await query.message.answer(texts.get_buy_views_text(bal), reply_markup=await get_buy_views_kb())


@router.callback_query(F.data == "buy:authors")
async def buy_authors_menu(query: CallbackQuery):
    await query.answer()
    user = await db.get_user(query.from_user.id)
    cost = await cfg.get_int('author_reveal_cost')
    try:
        await query.message.edit_text(texts.get_buy_authors_text(user.get('author_reveal_balance', 0), cost),
                                      reply_markup=await get_buy_authors_kb())
    except Exception:
        await query.message.answer(texts.get_buy_authors_text(user.get('author_reveal_balance', 0), cost),
                                   reply_markup=await get_buy_authors_kb())


@router.callback_query(F.data == "buy:uploads")
async def buy_uploads_menu(query: CallbackQuery):
    await query.answer()
    credits = (await db.get_user(query.from_user.id) or {}).get('extra_upload_credits', 0)
    try:
        await query.message.edit_text(texts.get_buy_uploads_text(credits),
                                      reply_markup=await get_buy_uploads_kb())
    except Exception:
        await query.message.answer(texts.get_buy_uploads_text(credits),
                                   reply_markup=await get_buy_uploads_kb())


@router.callback_query(F.data.startswith("buyviews:"))
async def buy_views_invoice(query: CallbackQuery, bot: Bot):
    _, count, stars = query.data.split(":")
    await _send_invoice(bot, query, kind="views", count=int(count), stars=int(stars),
                        title=f"{count} просмотров кружков")


@router.callback_query(F.data.startswith("buyauthors:"))
async def buy_authors_invoice(query: CallbackQuery, bot: Bot):
    _, count, stars = query.data.split(":")
    await _send_invoice(bot, query, kind="authors", count=int(count), stars=int(stars),
                        title=f"{count} просмотров авторов")


@router.callback_query(F.data.startswith("buyuploads:"))
async def buy_uploads_invoice(query: CallbackQuery, bot: Bot):
    _, count, stars = query.data.split(":")
    await _send_invoice(bot, query, kind="uploads", count=int(count), stars=int(stars),
                        title=f"{count} доп-загрузок кружков")


async def _send_invoice(bot: Bot, query: CallbackQuery, kind: str, count: int, stars: int, title: str):
    suffix = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    try:
        await bot.send_invoice(
            chat_id=query.from_user.id,
            title=title,
            description=f"Покупка: {title}",
            payload=f"{kind}_{count}_{suffix}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=stars)],
        )
        await query.answer("Счёт на оплату отправлен!")
    except Exception as e:
        logging.error(f"invoice error: {e}")
        await query.answer("Не удалось создать счёт. Попробуй позже.", show_alert=True)


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    sp = message.successful_payment
    payload = sp.invoice_payload or ""
    amount = sp.total_amount or 0
    charge_id = sp.telegram_payment_charge_id or payload
    parts = payload.split("_")
    kind = parts[0] if parts else ""
    count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    if kind not in ("views", "authors", "uploads", "hide"):
        await message.answer(f"{E.WARN} Не удалось распознать платёж. Свяжись с поддержкой.")
        return

    first_time = await db.log_star_payment(message.from_user.id, amount, kind, payload, charge_id)
    if not first_time:
        logging.warning(f"successful_payment: повтор charge_id={charge_id} — пропускаем начисление")
        user = await db.get_user(message.from_user.id) or {}
        await message.answer(f"{E.CHECK} Этот платёж уже зачислен.",
                             reply_markup=get_main_reply_kb(user.get('views_balance', 0)))
        return

    if kind == "views":
        await db.add_views_balance(message.from_user.id, count)
        msg = f"{E.CHECK} Оплата прошла! Начислено <b>+{count}</b> просмотров кружков."
    elif kind == "authors":
        await db.add_author_reveal_balance(message.from_user.id, count)
        msg = f"{E.CHECK} Оплата прошла! Начислено <b>+{count}</b> просмотров авторов."
    elif kind == "uploads":
        await db.add_extra_upload_credits(message.from_user.id, count)
        msg = f"{E.CHECK} Оплата прошла! Начислено <b>+{count}</b> доп-загрузок кружков."
    elif kind == "hide":
        await db.set_hide_authorship(message.from_user.id, True)
        msg = f"{E.LOCK} Готово! Теперь тебя не раскрыть как автора."

    await db.add_stars_spent(message.from_user.id, amount)
    user = await db.get_user(message.from_user.id) or {}
    await message.answer(msg, reply_markup=get_main_reply_kb(user.get('views_balance', 0)))



@router.inline_query()
async def inline_share(inline_query: InlineQuery, bot: Bot):
    q = inline_query.query or ""
    m = re.search(r"https://t\.me/[\w]+\?start=ref_\d+", q)
    if m:
        ref_link = m.group(0)
    else:
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{inline_query.from_user.id}"
    await inline_query.answer(
        results=[InlineQueryResultArticle(
            id="ref_share",
            title="Пригласить друга в Кружок",
            description="Отправить реферальную ссылку",
            input_message_content=InputTextMessageContent(
                message_text=texts.get_share_text(ref_link), parse_mode=None),
        )],
        cache_time=0,
    )
