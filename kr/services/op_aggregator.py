"""
Агрегатор ресурсов для ОП (Обязательная Подписка).
Каждый сервис вызывается один раз за запрос, результаты делятся между этапами 1 и 2 —
так избегаем дублей запросов и ошибок 429.
"""
import logging
from typing import List, Dict, Tuple
from urllib.parse import urlparse, parse_qs


def _target_key(item: dict) -> str:
    """Нормализованный ключ ресурса для дедупликации."""
    chat_id = item.get('chat_id')
    if chat_id:
        return f"chat:{chat_id}"
    source = item.get('source_service', '')
    identifier = item.get('identifier', '')
    if source and identifier:
        return f"{source}:{identifier}"
    url = item.get('url') or item.get('link') or ''
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


def _resolve_api_key(service: str, cfg: dict):
    """Возвращает API-ключ: сначала из БД-конфига, потом из ENV."""
    if cfg.get('api_key'):
        return cfg['api_key']
    import config
    return {
        'subgram': getattr(config, 'SUBGRAM_API_KEY', None),
        'botohub': getattr(config, 'BOTOHUB_API_KEY', None),
    }.get(service)


async def _fetch_service_channels(service: str, cfg: dict, user, limit: int) -> List[Dict]:
    """
    Получает сырые каналы из одного внешнего сервиса (без op_stage).
    Всегда закрывает aiohttp-сессию после запроса.
    """
    if limit <= 0:
        return []
    key = _resolve_api_key(service, cfg)
    if not key:
        return []

    lang = getattr(user, 'language_code', 'ru') or 'ru'
    is_premium = bool(getattr(user, 'is_premium', False))
    username = getattr(user, 'username', None)
    results: List[Dict] = []

    try:
        if service == 'subgram':
            from services.subgram import SubgramAPI
            api = SubgramAPI(key)
            try:
                tasks = await api.get_subgram_tasks(user)
                for t in (tasks or [])[:limit]:
                    link = t.get('link')
                    if link:
                        results.append({
                            'name':           t.get('resource_name') or t.get('title') or 'канал партнера',
                            'url':            link,
                            'check_type':     'subgram',
                            'source_service': 'subgram',
                        })
            finally:
                await api.close()

        elif service == 'botohub':
            from services.botohub import BotoHubAPI
            api = BotoHubAPI(key)
            try:
                links = await api.get_op_links(user.id, limit=limit)
                for link in links:
                    results.append({
                        'name':           'канал партнера',
                        'url':            link,
                        'check_type':     'botohub',
                        'source_service': 'botohub',
                    })
            finally:
                await api.close()

    except Exception as e:
        logging.error(f"[OP Aggregator] _fetch service={service}: {e}")

    return results


async def get_op_channels_both_stages(user, db) -> Tuple[List[Dict], List[Dict]]:
    """
    Получает каналы из всех включённых сервисов ОДИН РАЗ каждый
    и распределяет результаты по этапам 1 и 2.

    Возвращает (stage1_channels, stage2_channels).
    """
    all_cfgs   = await db.get_all_service_settings()
    s1_limit   = await db.get_op_stage_limit(1)
    s2_limit   = await db.get_op_stage_limit(2)
    is_premium = bool(getattr(user, 'is_premium', False))

    s1_channels: List[Dict] = []
    s2_channels: List[Dict] = []
    s1_seen: set = set()
    s2_seen: set = set()

    def _sort_key(cfg):
        p1 = cfg.get('op1_priority', 999) if cfg.get('op1_enabled') else 999
        p2 = cfg.get('op2_priority', 999) if cfg.get('op2_enabled') else 999
        return min(p1, p2)

    def _add(ch: dict, stage_list: list, seen: set, stage_num: int, limit: int) -> bool:
        if len(stage_list) >= limit:
            return False
        k = _target_key(ch)
        if k in seen:
            return False
        seen.add(k)
        stage_list.append({**ch, 'op_stage': stage_num})
        return True

    for cfg in sorted(all_cfgs, key=_sort_key):
        service = cfg['service']
        op1_en  = bool(cfg.get('op1_enabled'))
        op2_en  = bool(cfg.get('op2_enabled'))

        if not op1_en and not op2_en:
            logging.debug(f"[OP Agg] {service}: пропуск — оба этапа отключены")
            continue

        op1_max_raw = cfg.get('op1_max')
        op2_max_raw = cfg.get('op2_max')
        op1_max = (op1_max_raw if op1_max_raw is not None else 5) if op1_en else 0
        op2_max = (op2_max_raw if op2_max_raw is not None else 5) if op2_en else 0

        if op1_max <= 0 and op2_max <= 0:
            logging.debug(f"[OP Agg] {service}: пропуск — op1_max={op1_max} op2_max={op2_max} (оба ≤ 0)")
            continue

        s1_remaining = s1_limit - len(s1_channels)
        s2_remaining = s2_limit - len(s2_channels)
        s1_take = min(op1_max, s1_remaining)
        s2_take = min(op2_max, s2_remaining)

        logging.info(f"[OP Agg] {service}: op1_max={op1_max} op2_max={op2_max} "
                     f"s1_take={s1_take} s2_take={s2_take} "
                     f"(s1_filled={len(s1_channels)}/{s1_limit} s2_filled={len(s2_channels)}/{s2_limit})")

        if s1_take <= 0 and s2_take <= 0:
            logging.debug(f"[OP Agg] {service}: пропуск — нет свободных слотов (s1_take={s1_take} s2_take={s2_take})")
            continue

        try:
            if service == 'admin':
                if s1_take > 0:
                    raw1 = await db.get_admin_channels_for_op(stage=1, is_premium=is_premium)
                    for ch in raw1[:s1_take]:
                        _add({
                            'name':           ch.get('name'),
                            'url':            ch.get('url'),
                            'chat_id':        ch.get('chat_id'),
                            'check_type':     ch.get('check_type', 'none'),
                            'id':             ch.get('id'),
                            'source_service': 'admin',
                        }, s1_channels, s1_seen, 1, s1_limit)
                if s2_take > 0:
                    raw2 = await db.get_admin_channels_for_op(stage=2, is_premium=is_premium)
                    for ch in raw2[:s2_take]:
                        _add({
                            'name':           ch.get('name'),
                            'url':            ch.get('url'),
                            'chat_id':        ch.get('chat_id'),
                            'check_type':     ch.get('check_type', 'none'),
                            'id':             ch.get('id'),
                            'source_service': 'admin',
                        }, s2_channels, s2_seen, 2, s2_limit)

            else:
                total_needed = s1_take + s2_take
                channels = await _fetch_service_channels(service, cfg, user, total_needed)
                logging.info(f"[OP Agg] {service}: получено {len(channels)} каналов (нужно {total_needed})")

                for i, ch in enumerate(channels):
                    if i >= s1_take:
                        break
                    _add(ch, s1_channels, s1_seen, 1, s1_limit)

                for ch in channels[s1_take:s1_take + s2_take]:
                    _add(ch, s2_channels, s2_seen, 2, s2_limit)

        except Exception as e:
            logging.error(f"[OP Aggregator] service={service}: {e}")

    logging.info(f"[OP Agg] итого: Этап-1={len(s1_channels)}/{s1_limit} Этап-2={len(s2_channels)}/{s2_limit}")
    return s1_channels, s2_channels


async def get_op_channels_single(user, db) -> List[Dict]:
    """
    Одноэтапная ОП для Кружок-бота. В боте этап ОП всего один — берём только
    основной список ресурсов (этап 1). Внутреннее деление на этапы 1/2
    оставлено в БД для совместимости, но пользователю не показывается.
    """
    s1, _s2 = await get_op_channels_both_stages(user, db=db)
    seen = set()
    merged: List[Dict] = []
    for ch in s1:
        k = _target_key(ch)
        if k in seen:
            continue
        seen.add(k)
        merged.append({**ch, 'op_stage': 1})
    return merged


async def check_op_stage(
    channels_to_check: List[Dict],
    user_id: int,
    is_premium: bool,
    lang: str,
    db,
    bot,
) -> bool:
    """
    Проверяет, выполнены ли все задания для данного этапа ОП.
    Возвращает True если всё OK, False если хоть одно не выполнено.
    """
    stage_num = channels_to_check[0].get('op_stage', '?') if channels_to_check else '?'
    logging.info(f"[OP Check] user={user_id} stage={stage_num} — проверяем {len(channels_to_check)} каналов")

    for ch in (c for c in channels_to_check if c.get('source_service') == 'admin'):
        check_type = ch.get('check_type', 'none')
        chat_id = ch.get('chat_id')
        if check_type == 'none' or not chat_id:
            continue
        ok = False
        try:
            if await db.check_join_request(user_id=user_id, chat_id=chat_id):
                ok = True
            else:
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                ok = member.status in ('member', 'administrator', 'creator')
        except Exception as e:
            logging.error(f"[OP Check] admin channel {ch.get('name')}: {e}")
            ok = False
        if not ok:
            logging.info(f"[OP Check] БЛОК: admin канал '{ch.get('name')}' ({ch.get('url')})")
            return False

    subgram_chs = [c for c in channels_to_check if c.get('source_service') == 'subgram']
    if subgram_chs:
        cfg = await db.get_service_settings('subgram')
        key = _resolve_api_key('subgram', cfg or {})
        if key:
            from services.subgram import SubgramAPI
            api = SubgramAPI(key)
            try:
                links = [c['url'] for c in subgram_chs if c.get('url')]
                if links and not await api.check_op_links_batch(user_id, links):
                    logging.info(f"[OP Check] БЛОК: subgram — не все ссылки подписаны ({links})")
                    return False
            finally:
                await api.close()

    botohub_chs = [c for c in channels_to_check if c.get('source_service') == 'botohub']
    if botohub_chs:
        cfg = await db.get_service_settings('botohub')
        key = _resolve_api_key('botohub', cfg or {})
        if key:
            from services.botohub import BotoHubAPI
            api = BotoHubAPI(key)
            try:
                links = [c['url'] for c in botohub_chs if c.get('url')]
                done = await api.check_op_completion(user_id, links)
                logging.info(f"[OP Check] BotoHub: {'✓ выполнено' if done else 'не выполнено (не блокирует)'}")
            finally:
                await api.close()

    logging.info(f"[OP Check] user={user_id} stage={stage_num} — ВСЁ ПРОЙДЕНО ✓")
    return True
