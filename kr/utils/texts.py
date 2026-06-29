import re
from typing import Optional, Tuple

from aiogram.types import Message


def pe(emoji_id: str, fallback: str) -> str:
    """Премиум-эмодзи через HTML-тег tg-emoji."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def extract_icon_from_message(message: Message) -> Tuple[str, Optional[str]]:
    """
    Достаёт первый custom_emoji (премиум) из сообщения для иконки кнопки.
    Возвращает (чистый_текст, emoji_id | None).
    Используется админкой при добавлении кнопок.
    """
    text = message.text or message.caption or ""
    entities = list(message.entities or message.caption_entities or [])
    for entity in entities:
        if str(entity.type) == "custom_emoji":
            emoji_id = entity.custom_emoji_id
            before = text[:entity.offset]
            after = text[entity.offset + entity.length:]
            clean_text = (before + after).strip()
            return clean_text, emoji_id
    return text, None


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


class E:
    BACK      = pe("5465144256920324180", "⬅️")
    NEXT      = pe("5298640276208756843", "➡️")
    CHECK     = pe("5226788832011101883", "✅")
    GIRL      = pe("5291764338510538167", "🧍‍♀️")
    BOY       = pe("5292108060448271166", "🙎‍♂️")
    EYE       = pe("5285165181389777639", "👁")
    CHAT      = pe("5224415424493398515", "💬")
    PENCIL    = pe("5283140173029199387", "✏️")
    CALENDAR  = pe("5283065771310729985", "📅")
    CHECK2    = pe("5303362236268430955", "✅")
    QUESTION  = pe("5301218742645051855", "❓")
    FIRE      = pe("5305663058838835096", "🔥")
    WARN      = pe("5307535174953627548", "⚠️")
    DEV       = pe("5819154994967874788", "🧑‍💻")
    GIFT      = pe("5361986358015463601", "🎁")
    CART      = pe("5361781191722699867", "🛒")
    STARW     = pe("5362006552951690043", "🌟")
    GIFT2     = pe("5364047422626500018", "🎁")
    MONEY     = pe("5309795500277403547", "💰")
    QUESTION2 = pe("5312365458383474419", "❓")
    GEAR      = pe("5309974037772928528", "⚙️")
    CHECK3    = pe("5312326644764018054", "✅")
    GLOBE     = pe("5821388137443626414", "🌐")
    GEAR2     = pe("5818705028424141605", "⚙️")
    PHONE     = pe("5819062970998590994", "📱")
    LOCK      = pe("5821453562680448557", "🔐")
    POLICE    = pe("5818678700274617758", "👮‍♀️")
    CHECK4    = pe("5226832232655628145", "✅")
    STAR      = pe("5267500801240092311", "⭐")
    CASH      = pe("5197434882321567830", "💵")
    MAGNET    = pe("5377535110289576661", "🧲")
    SCOPE     = pe("5379999674193172777", "🔭")
    UPRIGHT   = pe("5429651785352501917", "↗️")
    PICK      = pe("5197371802136892976", "⛏")
    COIN      = pe("5199552030615558774", "🪙")
    PLANE     = pe("5201691993775818138", "🛫")
    SHIELD    = pe("5197288647275071607", "🛡")
    GLOBE2    = pe("5447410659077661506", "🌐")
    BOLT      = pe("5456140674028019486", "⚡️")
    COMET     = pe("5224607267797606837", "☄️")
    BAGS      = pe("5229064374403998351", "🛍")
    BANG      = pe("5440660757194744323", "‼️")
    UP        = pe("5449683594425410231", "🔼")
    CHART     = pe("5231200819986047254", "📊")
    PLUS      = pe("5397916757333654639", "➕")
    DIAMOND   = pe("5427168083074628963", "💎")
    STAR2     = pe("5438496463044752972", "⭐️")
    CROWN     = pe("5217822164362739968", "👑")
    SPARKLE   = pe("5325547803936572038", "✨")
    RAINBOW   = pe("5409109841538994759", "🌈")
    HEART     = pe("5370915878491665291", "❤️")
    DISLIKE   = pe("5447644880824181073", "👎")
    PLAY      = pe("5355012477883004708", "▶️")
    TV        = pe("5355012477883004708", "📺")


def mask_name(name: str) -> str:
    name = (name or "Аноним").strip()
    if not name:
        return "Аноним"
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" * min(len(name) - 1, 8)



def get_welcome_text(name: str) -> str:
    return (
        f"{E.STARW} <b>{name}, ты в Кружке</b>\n\n"
        f"Тут крутятся случайные видео-кружки живых людей:\n"
        f"{E.EYE} <i>листай чужие — бесплатно</i>\n"
        f"{E.FIRE} <i>отмечай тех, кто зацепил</i>\n"
        f"{E.LOCK} <i>захотел — узнай, кто за кадром</i>\n\n"
        f"<blockquote>Тапни <b>«Смотреть кружки»</b> на клавиатуре снизу — и поехали {E.NEXT}</blockquote>"
    )


def get_circle_caption(masked_author: str, likes: int = 0, dislikes: int = 0) -> str:
    return (
        f"{E.CHAT} <b>Кружок в эфире</b>\n"
        f"<blockquote>прислал(а): <b>{masked_author}</b></blockquote>"
    )


def get_op_text() -> str:
    return (
        f"{E.SHIELD} <b>Секундочку — мини-проверка</b>\n\n"
        f"Чтобы листать дальше, заскочи к партнёрам ниже {E.NEXT}\n"
        f"<i>Готово? Жми</i> «{E.CHECK} Проверить подписку» <i>— и лента снова открыта {E.FIRE}</i>"
    )


def get_op_resub_text() -> str:
    return (
        f"{E.WARN} <b>Ты отписался от наших партнёров</b>\n\n"
        f"Похоже, подписка пропала {E.NEXT} Пользоваться ботом без неё, к сожалению, "
        f"<b>нельзя</b> — это честное условие за бесплатные кружки {E.HEART}\n\n"
        f"Просто вернись к каналам ниже и жми «{E.CHECK} Проверить подписку» — "
        f"и лента снова твоя {E.FIRE}"
    )


def get_no_circles_text() -> str:
    return (
        f"{E.SCOPE} <b>Свежие кружки кончились</b>\n\n"
        f"<blockquote><i>Ты пролистал всё, что было. Загляни попозже — "
        f"подвезём новые {E.SPARKLE}</i></blockquote>"
    )


def get_out_of_views_text() -> str:
    return (
        f"{E.EYE} <b>Просмотры на нуле</b>\n\n"
        f"<i>Чем пополнить:</i>\n"
        f"{E.PLUS} <b>позови друзей</b> — каждый накидывает просмотров\n"
        f"{E.STAR} <b>возьми пакет за звёзды</b> — варианты ниже"
    )


def get_record_prompt_text() -> str:
    return (
        f"{E.PLAY} <b>Запиши свой кружок</b>\n\n"
        f"Сними прямо в Telegram <b>видео-сообщение</b> (кружок) и пришли его сюда {E.NEXT}\n"
        f"<blockquote><i>Тапни по иконке камеры в поле ввода и переключись в режим кружка. "
        f"Обычное видео или файл не подойдёт — нужен именно кружок.</i></blockquote>"
    )


def get_record_need_video_note_text() -> str:
    return (
        f"{E.WARN} Это не кружок. Нужно именно <b>видео-сообщение</b> "
        f"(круглое видео, записанное в Telegram). Попробуй ещё раз {E.NEXT}"
    )


def get_record_gender_text() -> str:
    return f"{E.QUESTION} <b>В какую ленту добавить кружок?</b>\n<i>Кому его показывать.</i>"


def get_circle_published_text(reward: int, *, paid: bool = False) -> str:
    if paid:
        tail = f"\n{E.STAR} <i>списан один платный слот загрузки</i>"
    else:
        tail = f"\n{E.PLAY} <b>+{reward}</b> к просмотрам кружков за это" if reward else ""
    return (
        f"{E.CHECK} <b>Кружок опубликован!</b>\n"
        f"Теперь его увидят другие в ленте.{tail}"
    )


def get_upload_limit_text(limit: int, credits: int) -> str:
    extra = (f"\n{E.STAR} Платных слотов в запасе: <b>{credits}</b>"
             if credits else
             f"\n<i>Можно докупить доп-загрузки за звёзды.</i>")
    return (
        f"{E.WARN} <b>На сегодня лимит загрузок исчерпан</b>\n"
        f"Бесплатно — до <b>{limit}</b> кружков в день.{extra}\n\n"
        f"<blockquote><i>Возвращайся завтра или возьми доп-загрузки {E.NEXT}</i></blockquote>"
    )


def get_buy_uploads_text(credits: int) -> str:
    return (
        f"{E.PLUS} <b>Доп-загрузки кружков</b>\n\n"
        f"{E.STAR} Платных слотов в запасе: <b>{credits}</b>\n\n"
        f"<blockquote><i>Каждый слот — одна загрузка сверх дневного лимита {E.BOLT}</i></blockquote>"
    )


def get_my_circles_text(count: int) -> str:
    return (
        f"{E.PLAY} <b>Мои кружки</b> — всего <b>{count}</b>\n"
        f"<i>Жми «Удалить», чтобы убрать кружок из ленты.</i>"
    )


def get_no_own_circles_text() -> str:
    return (
        f"{E.SCOPE} <b>У тебя пока нет своих кружков</b>\n"
        f"<i>Запиши первый — кнопка «Записать кружок» в профиле.</i>"
    )


def get_circle_deleted_text() -> str:
    return f"{E.CHECK} Кружок удалён."


def get_profile_text(name: str, username: str, *, circle_views: int, author_views: int,
                     referrals: int, views_balance: int, author_balance: int) -> str:
    uname = f" · @{username}" if username else ""
    return (
        f"{E.CHART} <b>Твоя статистика</b>\n\n"
        f"{E.BOY} <b>{name}</b>{uname}\n\n"
        f"{E.PLAY} Пролистано кружков: <b>{circle_views}</b>\n"
        f"{E.LOCK} Раскрыто авторов: <b>{author_views}</b>\n"
        f"{E.BOY} Позвал друзей: <b>{referrals}</b>\n\n"
        f"{E.EYE} Осталось просмотров: <b>{views_balance}</b>\n"
        f"{E.STAR} Осталось раскрытий: <b>{author_balance}</b>"
    )


def get_referral_text(ref_link: str, *, referrals: int, views_balance: int,
                      ref_views: int, ref_author_views: int) -> str:
    return (
        f"{E.GIFT} <b>Зови своих — получай просмотры</b>\n\n"
        f"За каждого, кто зайдёт по твоей ссылке:\n"
        f"{E.PLAY} <b>+{ref_views}</b> к просмотрам кружков\n"
        f"{E.LOCK} <b>+{ref_author_views}</b> к раскрытиям авторов\n\n"
        f"{E.BOY} Уже с тобой: <b>{referrals}</b> · {E.EYE} в запасе: <b>{views_balance}</b>\n\n"
        f"<i>Кидай ссылку друзьям:</i>\n"
        f"<code>{ref_link}</code>"
    )


def get_share_text(ref_link: str) -> str:
    return (
        "🎬 Случайные видео-кружки живых людей — листай и залипай\n\n"
        "🎁 Залетай по ссылке, на старте подкину бонусных просмотров:\n"
        f"{ref_link}"
    )


def get_feed_settings_text(gender: str) -> str:
    label = {'any': 'без разницы', 'male': 'парни', 'female': 'девушки'}.get(gender, 'без разницы')
    return (
        f"{E.GEAR} <b>Настройки ленты</b>\n\n"
        f"Сейчас крутим: <b>{label}</b>\n"
        f"<i>Выбери, чьи кружки показывать {E.NEXT}</i>"
    )


def get_report_prompt() -> str:
    return (
        f"{E.WARN} <b>На что жалуемся?</b>\n\n"
        f"<i>Напиши пару слов — реклама, спам, запрещёнка и т.п. "
        f"Модерация глянет и примет меры.</i>"
    )


def get_report_sent_text() -> str:
    return f"{E.CHECK} <b>Принято.</b> Передал модерации — спасибо, что чистишь ленту."


def get_buy_views_text(balance: int) -> str:
    return (
        f"{E.STAR} <b>Просмотры кружков</b>\n\n"
        f"{E.EYE} Сейчас в запасе: <b>{balance}</b>\n\n"
        f"<blockquote><i>Зачисляем мгновенно после оплаты {E.BOLT}</i></blockquote>"
    )


def get_buy_authors_text(balance: int, cost: int) -> str:
    return (
        f"{E.LOCK} <b>Раскрытия авторов</b>\n\n"
        f"{E.COIN} Цена: <b>{cost}</b>{E.STAR} за одно раскрытие\n"
        f"{E.EYE} В запасе: <b>{balance}</b>\n\n"
        f"<i>Купил — снова жми «Узнать автора», одно раскрытие спишется.</i>"
    )


def get_author_revealed_text(contact: str) -> str:
    return (
        f"{E.LOCK} <b>А вот и автор</b>\n"
        f"<blockquote>{contact}</blockquote>"
    )


def get_need_author_balance_text(cost: int) -> str:
    return (
        f"{E.LOCK} <b>Тут нужно раскрытие автора</b>\n\n"
        f"{E.COIN} Одно раскрытие — <b>{cost}</b>{E.STAR}\n\n"
        f"<i>Пополни запас раскрытий кнопкой ниже {E.NEXT}</i>"
    )


def get_banned_text() -> str:
    return (
        f"{E.POLICE} <b>Тебе сюда нельзя</b>\n\n"
        f"<i>Доступ закрыт за нарушение правил.</i>"
    )


DEFAULT_BAIT_TEXT = "у тебя новое видео-сообщение 👀"
DEFAULT_BAIT_BUTTON = "Посмотреть"



def get_anon_menu_text(gender: str, age) -> str:
    g = {'male': 'парень', 'female': 'девушка'}.get(gender, '—')
    return (
        f"{E.CHAT} <b>Анонимный чат</b>\n\n"
        f"{E.BOY} О тебе: <b>{g}</b>, <b>{age or '—'}</b>\n\n"
        f"<i>Жми «Найти собеседника» — соединю со случайным человеком. "
        f"Всё анонимно и только текстом {E.LOCK}</i>"
    )


def get_anon_ask_gender() -> str:
    return f"{E.BOY} <b>Ты кто?</b> Выбери пол для анонимного чата:"


def get_anon_ask_age() -> str:
    return f"{E.CALENDAR} <b>Сколько лет?</b> Просто пришли число (например, <code>21</code>):"


def get_anon_searching() -> str:
    return (
        f"{E.SCOPE} <b>Подбираю собеседника...</b>\n"
        f"<i>Найду — сразу соединю. Передумал — жми «Отмена поиска».</i>"
    )


def get_anon_matched() -> str:
    return (
        f"{E.SPARKLE} <b>Есть контакт!</b>\n\n"
        f"<i>Пиши — всё уходит анонимно. Только текст: фото, кружки и контакты не пройдут.</i>\n\n"
        f"<blockquote>{E.WARN} Свой юзернейм или ссылку скидывать бесполезно — такое не дойдёт.</blockquote>"
    )


def get_anon_partner_left() -> str:
    return f"{E.WARN} <b>Собеседник вышел.</b> Жми «Найти собеседника» — подберу нового."


def get_anon_only_text() -> str:
    return f"{E.WARN} Здесь летит <b>только текст</b> — без медиа и кружков."


def get_anon_leak_blocked() -> str:
    return (
        f"{E.LOCK} <b>Не отправил.</b>\n"
        f"<i>Похоже на контакт, ссылку или юзернейм — а это тут под запретом.</i>"
    )


def get_anon_revealed(contact: str) -> str:
    return f"{E.LOCK} <b>Кто по ту сторону:</b>\n<blockquote>{contact}</blockquote>"


def get_anon_offer_contact() -> str:
    return f"{E.LOCK} Хочешь узнать, с кем только что общался? Можно раскрыть контакт собеседника."


def get_ask_gender_text() -> str:
    return f"{E.STARW} Для начала укажи свой пол:"


def get_ask_feed_text() -> str:
    return f"{E.EYE} Какие кружки тебе показывать?"


def get_circle_blocked_notice() -> str:
    return (
        f"{E.WARN} <b>Твой кружок удалён</b>\n\n"
        f"Он нарушил правила сервиса и больше не показывается. "
        f"Будь добрее к правилам {E.HEART} — за повторные нарушения доступ к боту могут ограничить."
    )


def get_rules_text() -> str:
    return (
        "ℹ️ <b>Правила сервиса</b>\n\n"
        "• Отправляй только кружочки (видео-сообщения).\n"
        "• Запрещены материалы 18+, реклама, спам, оскорбления и незаконный контент.\n"
        "• Минимальная длина кружка — 3 секунды.\n"
        "• Уважай других и не злоупотребляй жалобами.\n\n"
        "<i>За нарушение доступ к боту может быть ограничен без предупреждения.</i>"
    )


def get_faq_text() -> str:
    return (
        "📋 <b>FAQ — частые вопросы</b>\n\n"
        "<b>1. Что дают за приглашённого друга?</b>\n"
        "ℹ️ За каждого нового друга по твоей ссылке — <b>+5 просмотров</b> кружков.\n\n"
        "<b>2. Как узнать автора кружка?</b>\n"
        "ℹ️ Нажми «Узнать автора» под кружком и оплати раскрытие звёздами ⭐.\n\n"
        "<b>3. Где взять реферальную ссылку?</b>\n"
        "ℹ️ Нажми «Пригласить друга» в меню.\n\n"
        "<b>4. Можно ли пересылать кружки?</b>\n"
        "ℹ️ Да. Главное — нормальное качество и без нарушений правил.\n\n"
        "<b>5. Есть ли ограничение на длину кружка?</b>\n"
        "ℹ️ Да, слишком короткие кружки не принимаются."
    )


def get_anon_need_balance(cost: int) -> str:
    return (
        f"{E.LOCK} <b>Чтобы вскрыть собеседника, нужно раскрытие</b>\n\n"
        f"{E.COIN} Одно раскрытие — <b>{cost}</b>{E.STAR}\n"
        f"<i>Пополни запас кнопкой ниже {E.NEXT}</i>"
    )


_LEAK_PATTERNS = [
    re.compile(r"@[A-Za-z0-9_]{3,}"),
    re.compile(r"(?:https?://|t\.me/|telegram\.me/|tg://)", re.I),
    re.compile(r"\b[A-Za-z0-9_]{4,}\.(?:me|com|ru|net|org|io)\b", re.I),
    re.compile(r"(?:\+?\d[\d \-]{6,}\d)"),
]


def contains_contact(text: str) -> bool:
    """True если в тексте есть похожее на контакт/ссылку/юзернейм."""
    if not text:
        return False
    for pat in _LEAK_PATTERNS:
        if pat.search(text):
            return True
    return False
