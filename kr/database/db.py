from datetime import datetime, timedelta

import asyncpg
import logging
from typing import Optional, List, Dict


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=5,
                max_size=50,
                command_timeout=60.0,
                max_inactive_connection_lifetime=300.0,
            )
            await self._initialize_db()
            logging.info("Успешное подключение к базе данных PostgreSQL.")
        except Exception as e:
            logging.error(f"Не удалось подключиться к базе данных: {e}")
            raise

    async def close(self):
        if self.pool:
            await self.pool.close()
            logging.info("Соединение с базой данных закрыто.")

    async def _initialize_db(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(32),
                    first_name VARCHAR(64) NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    has_passed_all_ops BOOLEAN NOT NULL DEFAULT FALSE,
                    referrer_id BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS has_started_op BOOLEAN NOT NULL DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_level INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reminder_message_id BIGINT;")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_links (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            await conn.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS op_passed_at TIMESTAMPTZ;
            """)
            await conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS has_passed_first_op BOOLEAN NOT NULL DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_op_passed_at TIMESTAMPTZ;")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS completed_tasks (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    task_provider VARCHAR(20) NOT NULL,
                    task_identifier TEXT NOT NULL,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, task_provider, task_identifier)
                );
            """)
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_completed_tasks_user_provider ON completed_tasks(user_id, task_provider);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_completed_tasks_user_provider уже существует или ошибка: {e}")
            
            await conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_link_id INTEGER REFERENCES ad_links(id) ON DELETE SET NULL;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_push_type VARCHAR(10);")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_push_sent_at TIMESTAMPTZ;")
            
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ DEFAULT NOW();")
            
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users(last_seen_at);",
                "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);",
                "CREATE INDEX IF NOT EXISTS idx_users_reminder ON users(reminder_level);",
                "CREATE INDEX IF NOT EXISTS idx_users_has_passed_all_ops ON users(has_passed_all_ops);",
                "CREATE INDEX IF NOT EXISTS idx_users_has_started_op ON users(has_started_op);"
            ]
            for index_query in indexes:
                try:
                    await conn.execute(index_query)
                except asyncpg.exceptions.PostgresError as e:
                    logging.warning(f"Индекс уже существует или ошибка при создании: {e}")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_channels (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    chat_id BIGINT,
                    op_stage INTEGER NOT NULL,
                    check_type VARCHAR(20) NOT NULL DEFAULT 'none', -- 'membership', 'join_request', 'none'
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                );
            """)
            await conn.execute("ALTER TABLE admin_channels ADD COLUMN IF NOT EXISTS premium_target VARCHAR(20) NOT NULL DEFAULT 'all';")
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_channels_active_stage ON admin_channels(is_active, op_stage);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_admin_channels_active_stage уже существует или ошибка: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist_users (
                    user_id BIGINT PRIMARY KEY,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist_exclusions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES whitelist_users(user_id) ON DELETE CASCADE,
                    admin_channel_id INTEGER NOT NULL REFERENCES admin_channels(id) ON DELETE CASCADE,
                    UNIQUE(user_id, admin_channel_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist_global_exclusions (
                    admin_channel_id INTEGER PRIMARY KEY REFERENCES admin_channels(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            await conn.execute("""
                 CREATE TABLE IF NOT EXISTS app_settings (
                    key VARCHAR(50) PRIMARY KEY,
                    value TEXT
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_links (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS join_requests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, chat_id)
                );
            """)
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_join_requests_user_chat ON join_requests(user_id, chat_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_join_requests_user_chat уже существует или ошибка: {e}")
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_click_history (
                    id SERIAL PRIMARY KEY,
                     link_id INTEGER REFERENCES ad_links(id) ON DELETE SET NULL,
                    user_id BIGINT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ad_click_history_link_user ON ad_click_history(link_id, user_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_ad_click_history_link_user уже существует или ошибка: {e}")
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ad_click_history_timestamp ON ad_click_history(timestamp DESC);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_ad_click_history_timestamp уже существует или ошибка: {e}")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_tasks (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    reward_attempts INTEGER NOT NULL DEFAULT 1,
                    chat_id BIGINT,
                    check_type VARCHAR(20) NOT NULL DEFAULT 'none',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_clicks (
                    id SERIAL PRIMARY KEY,
                    link_id INTEGER REFERENCES ad_links(id) ON DELETE SET NULL,
                    user_id BIGINT NOT NULL,
                    is_premium BOOLEAN NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(link_id, user_id)
                );
            """)
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ad_clicks_link_premium ON ad_clicks(link_id, is_premium);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_ad_clicks_link_premium уже существует или ошибка: {e}")
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ad_clicks_user ON ad_clicks(user_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_ad_clicks_user уже существует или ошибка: {e}")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS greetings (
                    id SERIAL PRIMARY KEY,
                    from_chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("ALTER TABLE greetings ADD COLUMN IF NOT EXISTS message_json JSONB;")
            await conn.execute("ALTER TABLE greetings ADD COLUMN IF NOT EXISTS display_count INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("UPDATE admin_channels SET op_stage = 1 WHERE op_stage <> 1;")
            await conn.execute("ALTER TABLE admin_channels ADD COLUMN IF NOT EXISTS shown_count INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE admin_channels ADD COLUMN IF NOT EXISTS passed_count INTEGER NOT NULL DEFAULT 0;")
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_shows (
                    id SERIAL PRIMARY KEY,
                    from_chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    message_json JSONB,
                    delay_minutes INTEGER NOT NULL,
                    target_audience VARCHAR(20) NOT NULL DEFAULT 'all',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_shows_sent (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    show_id INTEGER NOT NULL REFERENCES scheduled_shows(id) ON DELETE CASCADE,
                    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, show_id)
                );
            """)
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_shows_sent_user ON user_shows_sent(user_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_user_shows_sent_user уже существует или ошибка: {e}")
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_shows_d (
                    id SERIAL PRIMARY KEY,
                    from_chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    message_json JSONB,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    display_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_shows_n (
                    id SERIAL PRIMARY KEY,
                    from_chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    message_json JSONB,
                    delay_minutes INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    display_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_last_show_d (
                    user_id BIGINT PRIMARY KEY,
                    last_shown_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                -- Какие «Рекламы в ленте» (Показ D) пользователь уже видел —
                -- чтобы один и тот же показ не приходил повторно (уник на юзера).
                CREATE TABLE IF NOT EXISTS user_show_d_seen (
                    user_id BIGINT NOT NULL,
                    show_id INTEGER NOT NULL,
                    seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, show_id)
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS math_examples_completed (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    last_reset_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            
            try:
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_math_examples_user ON math_examples_completed(user_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Уникальный индекс ux_math_examples_user уже существует или ошибка: {e}")
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS special_ad_button (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    url TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    show_in_welcome BOOLEAN NOT NULL DEFAULT TRUE,
                    show_in_game BOOLEAN NOT NULL DEFAULT TRUE,
                    show_in_menu BOOLEAN NOT NULL DEFAULT TRUE,
                    show_in_gift_select BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "show_in_gift_select BOOLEAN NOT NULL DEFAULT FALSE;"
            )
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "icon_emoji_id TEXT;"
            )
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "button_style TEXT NOT NULL DEFAULT 'primary';"
            )
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "show_in_feed BOOLEAN NOT NULL DEFAULT TRUE;"
            )
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "show_in_profile BOOLEAN NOT NULL DEFAULT TRUE;"
            )
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "show_in_referral BOOLEAN NOT NULL DEFAULT FALSE;"
            )
            await conn.execute(
                "ALTER TABLE special_ad_button ADD COLUMN IF NOT EXISTS "
                "show_in_purchase BOOLEAN NOT NULL DEFAULT FALSE;"
            )

            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_daily_bonus_at TIMESTAMPTZ;")
            
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_attempts_used INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_reset_at TIMESTAMPTZ;")
            
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_gift TEXT;")
            
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_tasks_completed INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_examples_solved INTEGER NOT NULL DEFAULT 0;")
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_last_show_d_time ON user_last_show_d(last_shown_at);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_user_last_show_d_time уже существует или ошибка: {e}")
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_math_examples_user ON math_examples_completed(user_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_math_examples_user уже существует или ошибка: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS service_settings (
                    service      VARCHAR(20) PRIMARY KEY,
                    op1_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
                    op1_max      INTEGER NOT NULL DEFAULT 5,
                    op1_priority INTEGER NOT NULL DEFAULT 10,
                    op2_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
                    op2_max      INTEGER NOT NULL DEFAULT 5,
                    op2_priority INTEGER NOT NULL DEFAULT 10,
                    tasks_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
                    tasks_max       INTEGER NOT NULL DEFAULT 5,
                    tasks_priority  INTEGER NOT NULL DEFAULT 10,
                    api_key TEXT
                );
            """)
            _service_defaults = [
                ('admin',   True, 999, 1,  True, 999, 1,  True, 999, 1),
                ('subgram', True, 5,   2,  True, 5,   2,  True, 5,   2),
                ('botohub', True, 5,   3,  True, 5,   3,  True, 1,   3),
            ]
            for _sd in _service_defaults:
                await conn.execute("""
                    INSERT INTO service_settings
                        (service, op1_enabled, op1_max, op1_priority,
                         op2_enabled, op2_max, op2_priority,
                         tasks_enabled, tasks_max, tasks_priority)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (service) DO NOTHING
                """, *_sd)
            await conn.execute(
                "DELETE FROM service_settings WHERE service IN ('flyer','tgrass','grambee','gramads','hiviews')"
            )

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS op_stage_limits (
                    stage     INTEGER PRIMARY KEY,
                    max_total INTEGER NOT NULL DEFAULT 10
                );
            """)
            for _stage in (1, 2):
                await conn.execute("""
                    INSERT INTO op_stage_limits (stage, max_total)
                    VALUES ($1, 10)
                    ON CONFLICT (stage) DO NOTHING
                """, _stage)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_show_n_schedule (
                    id           SERIAL PRIMARY KEY,
                    user_id      BIGINT  NOT NULL,
                    delay_minutes INTEGER NOT NULL,
                    scheduled_at TIMESTAMPTZ NOT NULL,
                    sent_at      TIMESTAMPTZ
                );
            """)
            for _idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_show_n_sched_pending ON user_show_n_schedule(scheduled_at) WHERE sent_at IS NULL;",
                "CREATE INDEX IF NOT EXISTS idx_show_n_sched_user    ON user_show_n_schedule(user_id)      WHERE sent_at IS NULL;",
            ]:
                try:
                    await conn.execute(_idx_sql)
                except asyncpg.exceptions.PostgresError as e:
                    logging.warning(f"Индекс show_n_schedule уже существует или ошибка: {e}")


            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS views_balance INTEGER NOT NULL DEFAULT 10;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS author_reveal_balance INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS feed_gender VARCHAR(10) NOT NULL DEFAULT 'any';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS views_since_op INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS next_op_threshold INTEGER NOT NULL DEFAULT 7;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bait_index INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS circles_uploaded INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS circle_views_count INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS author_views_count INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrals_count INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS stars_spent INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hide_authorship BOOLEAN NOT NULL DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_uploads INTEGER NOT NULL DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_uploads_date DATE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS extra_upload_credits INTEGER NOT NULL DEFAULT 0;")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS circles (
                    id SERIAL PRIMARY KEY,
                    owner_id BIGINT,
                    file_id TEXT NOT NULL,
                    is_bait BOOLEAN NOT NULL DEFAULT FALSE,
                    bait_order INTEGER,
                    fake_author_name TEXT,
                    fake_author_username TEXT,
                    fake_author_url TEXT,
                    gender VARCHAR(10) NOT NULL DEFAULT 'any',
                    likes INTEGER NOT NULL DEFAULT 0,
                    dislikes INTEGER NOT NULL DEFAULT 0,
                    views INTEGER NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            for _c_idx in [
                "CREATE INDEX IF NOT EXISTS idx_circles_bait ON circles(is_bait, bait_order) WHERE is_active = TRUE;",
                "CREATE INDEX IF NOT EXISTS idx_circles_active ON circles(is_active, is_blocked, gender);",
                "CREATE INDEX IF NOT EXISTS idx_circles_owner ON circles(owner_id);",
            ]:
                try:
                    await conn.execute(_c_idx)
                except asyncpg.exceptions.PostgresError as e:
                    logging.warning(f"Индекс circles: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS circle_views (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    circle_id INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
                    reaction VARCHAR(10),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, circle_id)
                );
            """)
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_circle_views_user ON circle_views(user_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс circle_views: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS author_reveals (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    circle_id INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, circle_id)
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    reporter_id BIGINT NOT NULL,
                    target_type VARCHAR(20) NOT NULL,
                    target_circle_id INTEGER,
                    target_user_id BIGINT,
                    reason TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'open',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at DESC);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс reports: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bait_messages (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    button_text TEXT NOT NULL DEFAULT 'Посмотреть',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bait_sent_at TIMESTAMPTZ;")
            await conn.execute("ALTER TABLE bait_messages ADD COLUMN IF NOT EXISTS delay_min INTEGER NOT NULL DEFAULT 30;")
            await conn.execute("ALTER TABLE bait_messages ADD COLUMN IF NOT EXISTS delay_max INTEGER NOT NULL DEFAULT 90;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_bait_schedule (
                    user_id BIGINT NOT NULL,
                    bait_id INTEGER NOT NULL,
                    fire_at TIMESTAMPTZ NOT NULL,
                    anchor  TIMESTAMPTZ NOT NULL,
                    sent    BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (user_id, bait_id)
                );
            """)
            try:
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_user_bait_due ON user_bait_schedule(fire_at) WHERE sent = FALSE;")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс idx_user_bait_due: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS star_payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    kind VARCHAR(30) NOT NULL,
                    payload TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_star_payments_time ON star_payments(created_at DESC);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Индекс star_payments: {e}")
            try:
                await conn.execute("ALTER TABLE star_payments ADD COLUMN IF NOT EXISTS charge_id TEXT;")
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_star_payments_charge ON star_payments(charge_id);")
            except asyncpg.exceptions.PostgresError as e:
                logging.warning(f"Миграция star_payments.charge_id: {e}")

            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS anon_gender VARCHAR(10);")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS anon_age INTEGER;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_anon_partner BIGINT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(10);")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded BOOLEAN NOT NULL DEFAULT FALSE;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS anon_queue (
                    user_id BIGINT PRIMARY KEY,
                    gender VARCHAR(10),
                    age INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS anon_pairs (
                    id SERIAL PRIMARY KEY,
                    user_a BIGINT NOT NULL,
                    user_b BIGINT NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            for _a_idx in [
                "CREATE INDEX IF NOT EXISTS idx_anon_pairs_a ON anon_pairs(user_a) WHERE active;",
                "CREATE INDEX IF NOT EXISTS idx_anon_pairs_b ON anon_pairs(user_b) WHERE active;",
                "CREATE INDEX IF NOT EXISTS idx_anon_queue_created ON anon_queue(created_at);",
            ]:
                try:
                    await conn.execute(_a_idx)
                except asyncpg.exceptions.PostgresError as e:
                    logging.warning(f"Индекс anon: {e}")

            import config as _cfg
            for _k, _v in getattr(_cfg, 'KRUZHOK_DEFAULTS', {}).items():
                await conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                    _k, _v,
                )

        logging.info("Инициализация таблиц базы данных завершена.")

    async def log_join_request(self, user_id: int, chat_id: int):
        query = """
            INSERT INTO join_requests (user_id, chat_id) VALUES ($1, $2)
            ON CONFLICT (user_id, chat_id) DO NOTHING;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id, chat_id)

    async def add_admin_task(self, name: str, url: str, reward_attempts: int, check_type: str, chat_id: int = None):
        query = """
            INSERT INTO admin_tasks (name, url, reward_attempts, check_type, chat_id)
            VALUES ($1, $2, $3, $4, $5)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, name, url, reward_attempts, check_type, chat_id)

    async def get_all_admin_tasks(self) -> List[Dict]:
        query = "SELECT id, name, url, reward_attempts, check_type FROM admin_tasks ORDER BY id"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(record) for record in records]

    async def get_active_admin_tasks(self) -> List[Dict]:
        query = "SELECT id, name, url, reward_attempts, chat_id, check_type FROM admin_tasks WHERE is_active = TRUE ORDER BY id"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(record) for record in records]

    async def get_admin_task_by_id(self, task_id: int) -> Optional[Dict]:
        query = "SELECT * FROM admin_tasks WHERE id = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, task_id)
            return dict(record) if record else None

    async def delete_admin_task(self, task_id: int):
        query = "DELETE FROM admin_tasks WHERE id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, task_id)

    async def mark_op_as_started(self, user_id: int):
        query = "UPDATE users SET has_started_op = TRUE WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)

    async def set_first_op_passed(self, user_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE users SET has_passed_first_op = TRUE, first_op_passed_at = NOW() WHERE user_id = $1 AND has_passed_first_op = FALSE",
                user_id
            )

    async def get_users_for_reminders(self, current_time: datetime) -> List[Dict]:
        query = """
            SELECT user_id, first_name, reminder_level, last_reminder_message_id
            FROM users
            WHERE
                has_passed_all_ops = FALSE AND
                has_started_op = FALSE AND
                reminder_level >= 0 AND
                (NOW() - created_at) < interval '1 day' AND
                (
                    (reminder_level = 0 AND created_at + interval '10 minutes' < $1) OR
                    (reminder_level = 1 AND created_at + interval '30 minutes' < $1) OR
                    (reminder_level = 2 AND created_at + interval '60 minutes' < $1) OR
                    (reminder_level > 2 AND last_push_sent_at + interval '60 minutes' < $1)
                )
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, current_time)
            return [dict(r) for r in records]

    async def get_ad_link_by_name(self, name: str) -> Optional[dict]:
        query = "SELECT id, name FROM ad_links WHERE name = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, name)
            return dict(record) if record else None

    async def update_user_reminder_info(self, user_id: int, level: int, message_id: int):
        query = """
            UPDATE users 
            SET reminder_level = $1, last_reminder_message_id = $2, last_push_sent_at = NOW() 
            WHERE user_id = $3
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, level, message_id, user_id)

    async def update_user_reminder_level(self, user_id: int, level: int):
        query = "UPDATE users SET reminder_level = $1, last_push_sent_at = NOW() WHERE user_id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, level, user_id)

    async def get_users_for_push(self, days: int) -> List[dict]:
        exclude_push_type = f"{days}-day"
        query = """
            SELECT user_id FROM users
            WHERE
                last_seen_at < NOW() - ($1 || ' days')::interval AND
                last_seen_at >= NOW() - (($1::int + 1) || ' days')::interval AND
                (last_push_type IS NULL OR last_push_type != $2)
        """
        async with self.pool.acquire() as conn:
            interval_days = str(days)
            records = await conn.fetch(query, interval_days, exclude_push_type)
            return [dict(record) for record in records]

    async def update_user_push_status(self, user_id: int, push_type: str):
        query = "UPDATE users SET last_push_type = $1, last_push_sent_at = NOW() WHERE user_id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, push_type, user_id)

    async def check_join_request(self, user_id: int, chat_id: int) -> bool:
        query = "SELECT EXISTS (SELECT 1 FROM join_requests WHERE user_id = $1 AND chat_id = $2);"
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval(query, user_id, chat_id)
            return exists

    async def add_ad_link(self, name: str, description: str = None) -> Optional[dict]:
        query = "INSERT INTO ad_links (name, description) VALUES ($1, $2) RETURNING id, name;"
        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(query, name, description)
                return dict(record)
        except asyncpg.UniqueViolationError:
            return None

    async def get_all_ad_links(self) -> List[dict]:
        query = "SELECT id, name, description, created_at FROM ad_links ORDER BY created_at DESC"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def get_ad_links_paginated(self, page: int, per_page: int) -> (List[dict], int):
        """Страница ad_links и общее количество."""
        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 10

        offset = (page - 1) * per_page
        async with self.pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT id, name, description, created_at
                FROM ad_links
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                per_page, offset
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM ad_links")
        return [dict(r) for r in records], int(total or 0)

    async def delete_ad_link(self, link_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM ad_links WHERE id = $1", link_id)

    async def get_ad_link_users_count(self) -> int:
        query = "SELECT COUNT(DISTINCT user_id) FROM ad_clicks;"
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(query)
            return count or 0

    async def get_ad_link_stats(self, link_id: int) -> dict:
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow("""
                WITH ad_stats AS (
                    SELECT 
                        COUNT(*) as unique_users,
                        COUNT(*) FILTER (WHERE is_premium = TRUE) as premium_clicks
                    FROM ad_clicks 
                    WHERE link_id = $1
                ),
                click_history AS (
                    SELECT COUNT(*) as total_clicks
                    FROM ad_click_history 
                    WHERE link_id = $1
                ),
                op_stats AS (
                    SELECT
                        COUNT(DISTINCT ac.user_id) FILTER (WHERE u.has_passed_first_op = TRUE) as op_1_users,
                        COUNT(DISTINCT ac.user_id) FILTER (WHERE u.has_passed_all_ops = TRUE) as op_2_users
                    FROM ad_clicks ac
                    JOIN users u ON ac.user_id = u.user_id
                    WHERE ac.link_id = $1
                )
                SELECT 
                    COALESCE(ad_stats.unique_users, 0) as unique_users,
                    COALESCE(ad_stats.premium_clicks, 0) as premium_clicks,
                    GREATEST(COALESCE(click_history.total_clicks, 0), COALESCE(ad_stats.unique_users, 0)) as total_clicks,
                    COALESCE(op_stats.op_1_users, 0) as completed_op_1_users,
                    COALESCE(op_stats.op_2_users, 0) as completed_op_2_users
                FROM ad_stats, click_history, op_stats
            """, link_id)
            
            return {
                'total_clicks': stats['total_clicks'],
                'unique_users': stats['unique_users'],
                'premium_clicks': stats['premium_clicks'],
                'unique_premium_users': stats['premium_clicks'],
                'completed_op_users': stats['completed_op_2_users'],
                'completed_op_1_users': stats['completed_op_1_users'],
                'completed_op_2_users': stats['completed_op_2_users']
            }

    async def get_self_growth_users_count(self) -> int:
        query = "SELECT COUNT(*) FROM users WHERE ad_link_id IS NULL;"
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(query)
            return count or 0

    async def get_users_count_by_source(self, source_type: str) -> int:
        """Подсчитывает пользователей по их источнику ('ad' или 'organic')."""
        query = "SELECT COUNT(*) FROM users WHERE source = $1"
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(query, source_type)
            return count or 0

    async def get_or_create_user(self, user_id: int, username: str, first_name: str, is_premium: bool,
                                 referrer_id: int = None, ad_link_name: str = None):
        async with self.pool.acquire() as conn:
            simple_update = await conn.fetchrow(
                """
                UPDATE users SET 
                    username = $2,
                    first_name = $3,
                    last_seen_at = NOW()
                WHERE user_id = $1
                RETURNING *
                """,
                user_id, username, first_name
            )
            
            if simple_update:
                if ad_link_name:
                    try:
                        link_id_existing = await conn.fetchval("SELECT id FROM ad_links WHERE name = $1", ad_link_name)
                        if link_id_existing:
                            await conn.execute(
                                """
                                INSERT INTO ad_click_history (link_id, user_id)
                                SELECT $1, $2
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM ad_click_history
                                    WHERE link_id = $1 AND user_id = $2 AND timestamp > NOW() - interval '3 hours'
                                )
                                """,
                                link_id_existing, user_id
                            )
                    except Exception as e:
                        logging.warning(f"Ошибка логирования клика по рекламной ссылке для существующего пользователя {user_id}: {e}")
                return dict(simple_update)
            
            async with conn.transaction():
                link_id = None
                if ad_link_name:
                    link_id = await conn.fetchval("SELECT id FROM ad_links WHERE name = $1", ad_link_name)
                
                if link_id:
                    await conn.execute(
                        "INSERT INTO ad_click_history (link_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        link_id, user_id
                    )
                    await conn.execute(
                        """
                        INSERT INTO ad_clicks (link_id, user_id, is_premium)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (link_id, user_id) DO NOTHING
                        """,
                        link_id, user_id, is_premium
                    )

                user_source = 'ad' if link_id else 'organic'
                
                query = """
                    INSERT INTO users (user_id, username, first_name, referrer_id, ad_link_id, source)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_seen_at = NOW()
                    RETURNING *;
                """
                record = await conn.fetchrow(
                    query,
                    user_id,
                    username,
                    first_name,
                    referrer_id,
                    link_id,
                    user_source
                )
                return dict(record) if record else None


    async def get_user(self, user_id: int):
        async with self.pool.acquire() as connection:
            user_record = await connection.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return dict(user_record) if user_record else None

    async def update_user_attempts(self, user_id: int, diff: int):
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                "UPDATE users SET attempts = attempts + $1 WHERE user_id = $2 RETURNING attempts",
                diff, user_id
            )

    async def add_completed_task(self, user_id: int, task_provider: str, task_identifier: str):
        query = """
            INSERT INTO completed_tasks (user_id, task_provider, task_identifier)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, task_provider, task_identifier) DO NOTHING;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id, task_provider, task_identifier)

    async def get_completed_tasks_by_provider(self, user_id: int, provider: str) -> List[str]:
        query = "SELECT task_identifier FROM completed_tasks WHERE user_id = $1 AND task_provider = $2"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, user_id, provider)
            return [record['task_identifier'] for record in records]

    async def add_admin_channel(self, name: str, url: str, op_stage: int, check_type: str, premium_target: str, chat_id: int = None):
        query = """
             INSERT INTO admin_channels (name, url, op_stage, check_type, premium_target, chat_id)
             VALUES ($1, $2, $3, $4, $5, $6)
         """
        async with self.pool.acquire() as conn:
            await conn.execute(query, name, url, op_stage, check_type, premium_target, chat_id)

    async def get_all_admin_channels(self) -> List[Dict]:
        query = "SELECT id, name, url, op_stage, check_type, chat_id, premium_target, shown_count, passed_count FROM admin_channels ORDER BY op_stage, id"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(record) for record in records]

    async def increment_channels_shown(self, channel_ids: list):
        if not channel_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE admin_channels SET shown_count = shown_count + 1 WHERE id = ANY($1::int[])",
                channel_ids,
            )

    async def increment_channels_passed(self, channel_ids: list):
        if not channel_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE admin_channels SET passed_count = passed_count + 1 WHERE id = ANY($1::int[])",
                channel_ids,
            )

    async def get_admin_channels_for_op(self, stage: int, is_premium: bool) -> List[Dict]:
        query = """
            SELECT id, name, url, chat_id, check_type, premium_target
            FROM admin_channels
            WHERE op_stage = $1 AND is_active = TRUE
            AND (
                premium_target = 'all' OR
                (premium_target = 'premium' AND $2 = TRUE) OR
                (premium_target = 'non_premium' AND $2 = FALSE)
            )
            ORDER BY id
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, stage, is_premium)
            return [dict(record) for record in records]

    async def get_all_admin_channels_ordered(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, url, chat_id, check_type, op_stage FROM admin_channels WHERE is_active = TRUE ORDER BY op_stage, id")
            return [dict(r) for r in rows]

    async def delete_admin_channel(self, channel_id: int):
        query = "DELETE FROM admin_channels WHERE id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, channel_id)

    async def set_user_attempts(self, user_id: int, amount: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE users SET attempts = $1 WHERE user_id = $2", amount, user_id)

    async def set_op_passed(self, user_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE users SET has_passed_all_ops = TRUE, op_passed_at = NOW() WHERE user_id = $1",
                user_id
            )

    async def add_whitelist_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
                user_id
            )

    async def get_whitelist_users(self) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM whitelist_users ORDER BY added_at DESC")
            return [r['user_id'] for r in rows]

    async def is_user_in_whitelist(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT EXISTS (SELECT 1 FROM whitelist_users WHERE user_id = $1)", user_id)

    async def get_whitelist_exclusions(self, user_id: int) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT admin_channel_id FROM whitelist_exclusions WHERE user_id = $1",
                user_id
            )
            return [r['admin_channel_id'] for r in rows]

    async def toggle_whitelist_exclusion(self, user_id: int, admin_channel_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM whitelist_exclusions WHERE user_id = $1 AND admin_channel_id = $2",
                    user_id, admin_channel_id
                )
                if exists:
                    await conn.execute(
                        "DELETE FROM whitelist_exclusions WHERE user_id = $1 AND admin_channel_id = $2",
                        user_id, admin_channel_id
                    )
                    return False
                else:
                    await conn.execute(
                        "INSERT INTO whitelist_exclusions (user_id, admin_channel_id) VALUES ($1, $2)",
                        user_id, admin_channel_id
                    )
                    return True

    async def get_whitelist_global_exclusions(self) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT admin_channel_id FROM whitelist_global_exclusions")
            return [r['admin_channel_id'] for r in rows]

    async def toggle_whitelist_global_exclusion(self, admin_channel_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM whitelist_global_exclusions WHERE admin_channel_id = $1",
                    admin_channel_id
                )
                if exists:
                    await conn.execute(
                        "DELETE FROM whitelist_global_exclusions WHERE admin_channel_id = $1",
                        admin_channel_id
                    )
                    return False
                else:
                    await conn.execute(
                        "INSERT INTO whitelist_global_exclusions (admin_channel_id) VALUES ($1)",
                        admin_channel_id
                    )
                    return True

    async def set_setting(self, key: str, value: str):
        query = """
            INSERT INTO app_settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, key, value)

    async def get_setting(self, key: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT value FROM app_settings WHERE key = $1", key)

    async def get_all_settings(self) -> dict:
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT key, value FROM app_settings;")
            return {record['key']: record['value'] for record in records}

    async def get_all_user_ids(self) -> list:
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT user_id FROM users;")
            return [record['user_id'] for record in records]

    async def get_users_count(self, period: str = "total") -> int:
        async with self.pool.acquire() as conn:
            if period == "total":
                query = "SELECT count(*) FROM users;"
                return await conn.fetchval(query)
            elif period == "today":
                query = "SELECT count(*) FROM users WHERE created_at >= current_date;"
            elif period == "yesterday":
                query = "SELECT count(*) FROM users WHERE created_at >= current_date - interval '1 day' AND created_at < current_date;"
            elif period == "week":
                query = "SELECT count(*) FROM users WHERE created_at >= current_date - interval '7 days';"
            else:
                return 0
            return await conn.fetchval(query)

    async def get_op_passed_count(self, period: str = "total") -> int:
        async with self.pool.acquire() as conn:
            if period == "total":
                query = "SELECT count(*) FROM users WHERE has_passed_all_ops = TRUE;"
            elif period == "today":
                query = "SELECT count(*) FROM users WHERE op_passed_at >= current_date;"
            elif period == "yesterday":
                query = "SELECT count(*) FROM users WHERE op_passed_at >= current_date - interval '1 day' AND op_passed_at < current_date;"
            elif period == "week":
                query = "SELECT count(*) FROM users WHERE op_passed_at >= current_date - interval '7 days';"
            else:
                return 0
            return await conn.fetchval(query)


    async def get_referrer_id(self, user_id: int) -> Optional[int]:
        async with self.pool.acquire() as connection:
            return await connection.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)

    async def add_completed_subgram_task(self, user_id: int, link: str):
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE users SET completed_subgram_tasks = array_append(completed_subgram_tasks, $1) WHERE user_id = $2 AND NOT ($1 = ANY(completed_subgram_tasks))",
                link, user_id
            )

    async def add_greeting(self, from_chat_id: int, message_id: int, message_json: dict = None):
        query = """
            INSERT INTO greetings (from_chat_id, message_id, message_json) VALUES ($1, $2, $3)
        """
        async with self.pool.acquire() as conn:
            import json
            json_value = json.dumps(message_json) if message_json is not None else None
            await conn.execute(query, from_chat_id, message_id, json_value)

    async def get_all_greetings(self) -> List[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json, is_active, display_count, created_at FROM greetings ORDER BY id DESC"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def increment_greeting_count(self, greeting_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE greetings SET display_count = display_count + 1 WHERE id = $1", greeting_id)

    async def update_greeting(self, greeting_id: int, from_chat_id: int, message_id: int, message_json: dict = None):
        query = "UPDATE greetings SET from_chat_id = $2, message_id = $3, message_json = $4 WHERE id = $1"
        async with self.pool.acquire() as conn:
            import json
            json_value = json.dumps(message_json) if message_json is not None else None
            await conn.execute(query, greeting_id, from_chat_id, message_id, json_value)

    async def get_greeting_by_id(self, greeting_id: int) -> Optional[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json, is_active, display_count FROM greetings WHERE id = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, greeting_id)
            return dict(record) if record else None

    async def delete_greeting(self, greeting_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM greetings WHERE id = $1", greeting_id)

    async def get_random_greeting(self) -> Optional[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json FROM greetings WHERE is_active = TRUE ORDER BY RANDOM() LIMIT 1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query)
            return dict(record) if record else None

    async def add_scheduled_show(self, from_chat_id: int, message_id: int, delay_minutes: int, target_audience: str, message_json: dict = None):
        query = """
            INSERT INTO scheduled_shows (from_chat_id, message_id, delay_minutes, target_audience, message_json)
            VALUES ($1, $2, $3, $4, $5)
        """
        async with self.pool.acquire() as conn:
            import json
            json_value = json.dumps(message_json) if message_json is not None else None
            await conn.execute(query, from_chat_id, message_id, delay_minutes, target_audience, json_value)

    async def get_all_scheduled_shows(self) -> List[Dict]:
        query = """
            SELECT id, from_chat_id, message_id, message_json, delay_minutes, target_audience, is_active, created_at 
            FROM scheduled_shows 
            ORDER BY delay_minutes ASC, id DESC
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def get_active_scheduled_shows(self) -> List[Dict]:
        query = """
            SELECT id, from_chat_id, message_id, message_json, delay_minutes, target_audience
            FROM scheduled_shows 
            WHERE is_active = TRUE 
            ORDER BY delay_minutes ASC
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def delete_scheduled_show(self, show_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM scheduled_shows WHERE id = $1", show_id)

    async def check_show_sent_to_user(self, user_id: int, show_id: int) -> bool:
        query = "SELECT EXISTS (SELECT 1 FROM user_shows_sent WHERE user_id = $1 AND show_id = $2);"
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval(query, user_id, show_id)
            return exists

    async def mark_show_as_sent(self, user_id: int, show_id: int):
        query = """
            INSERT INTO user_shows_sent (user_id, show_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id, show_id) DO NOTHING;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id, show_id)

    async def get_user_math_progress(self, user_id: int) -> Optional[Dict]:
        query = """
            SELECT correct_count, total_count, last_reset_at
            FROM math_examples_completed
            WHERE user_id = $1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, user_id)
            return dict(record) if record else None

    async def update_math_progress(self, user_id: int, is_correct: bool):
        query = """
            INSERT INTO math_examples_completed (user_id, correct_count, total_count)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id) DO UPDATE SET
                correct_count = math_examples_completed.correct_count + $2,
                total_count = math_examples_completed.total_count + 1;
        """
        correct_increment = 1 if is_correct else 0
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id, correct_increment)

    async def reset_math_progress(self, user_id: int):
        query = """
            UPDATE math_examples_completed
            SET correct_count = 0, total_count = 0, last_reset_at = NOW()
            WHERE user_id = $1
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)

    async def add_show_d(self, from_chat_id: int, message_id: int, message_json: dict = None):
        query = """
            INSERT INTO ad_shows_d (from_chat_id, message_id, message_json)
            VALUES ($1, $2, $3)
        """
        async with self.pool.acquire() as conn:
            import json
            json_value = json.dumps(message_json) if message_json is not None else None
            await conn.execute(query, from_chat_id, message_id, json_value)

    async def get_all_shows_d(self) -> List[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json, is_active, display_count, created_at FROM ad_shows_d ORDER BY id DESC"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def get_random_show_d(self) -> Optional[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json FROM ad_shows_d WHERE is_active = TRUE ORDER BY RANDOM() LIMIT 1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query)
            return dict(record) if record else None

    async def get_random_show_d_unseen(self, user_id: int) -> Optional[Dict]:
        """Случайный активный Показ D, который этот пользователь ещё НЕ видел."""
        query = """
            SELECT id, from_chat_id, message_id, message_json
            FROM ad_shows_d
            WHERE is_active = TRUE
              AND id NOT IN (SELECT show_id FROM user_show_d_seen WHERE user_id = $1)
            ORDER BY RANDOM() LIMIT 1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, user_id)
            return dict(record) if record else None

    async def mark_show_d_seen(self, user_id: int, show_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_show_d_seen (user_id, show_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_id, show_id,
            )

    async def get_show_d_by_id(self, show_id: int) -> Optional[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json FROM ad_shows_d WHERE id = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, show_id)
            return dict(record) if record else None

    async def delete_show_d(self, show_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM ad_shows_d WHERE id = $1", show_id)

    async def increment_show_d_count(self, show_id: int):
        query = "UPDATE ad_shows_d SET display_count = display_count + 1 WHERE id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, show_id)

    async def add_show_n(self, from_chat_id: int, message_id: int, delay_minutes: int, message_json: dict = None):
        query = """
            INSERT INTO ad_shows_n (from_chat_id, message_id, delay_minutes, message_json)
            VALUES ($1, $2, $3, $4)
        """
        async with self.pool.acquire() as conn:
            import json
            json_value = json.dumps(message_json) if message_json is not None else None
            await conn.execute(query, from_chat_id, message_id, delay_minutes, json_value)

    async def get_all_shows_n(self) -> List[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json, delay_minutes, is_active, display_count, created_at FROM ad_shows_n ORDER BY delay_minutes ASC, id DESC"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def get_shows_n_by_delay(self, delay_minutes: int) -> List[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json FROM ad_shows_n WHERE delay_minutes = $1 AND is_active = TRUE"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, delay_minutes)
            return [dict(r) for r in records]

    async def get_show_n_by_id(self, show_id: int) -> Optional[Dict]:
        query = "SELECT id, from_chat_id, message_id, message_json FROM ad_shows_n WHERE id = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, show_id)
            return dict(record) if record else None

    async def delete_show_n(self, show_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM ad_shows_n WHERE id = $1", show_id)

    async def increment_show_n_count(self, show_id: int):
        query = "UPDATE ad_shows_n SET display_count = display_count + 1 WHERE id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, show_id)


    async def schedule_shows_n_for_user(self, user_id: int) -> int:
        """Перепланирует активные Показы N для пользователя; возвращает число записей."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM user_show_n_schedule WHERE user_id = $1 AND sent_at IS NULL",
                    user_id,
                )
                delays = await conn.fetch(
                    "SELECT DISTINCT delay_minutes FROM ad_shows_n WHERE is_active = TRUE ORDER BY delay_minutes ASC"
                )
                if not delays:
                    return 0
                rows = [(user_id, r["delay_minutes"]) for r in delays]
                await conn.executemany(
                    """INSERT INTO user_show_n_schedule (user_id, delay_minutes, scheduled_at)
                       VALUES ($1, $2, NOW() + ($2::int * INTERVAL '1 minute'))""",
                    rows,
                )
                return len(rows)

    async def cancel_pending_shows_n_for_user(self, user_id: int):
        """Отменяет (удаляет) все неотправленные записи Показов N для пользователя."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM user_show_n_schedule WHERE user_id = $1 AND sent_at IS NULL",
                user_id,
            )

    async def get_pending_shows_n(self, limit: int = 100) -> List[Dict]:
        """Записи Показов N, время которых наступило."""
        async with self.pool.acquire() as conn:
            records = await conn.fetch(
                """SELECT id, user_id, delay_minutes
                   FROM user_show_n_schedule
                   WHERE sent_at IS NULL AND scheduled_at <= NOW()
                   ORDER BY scheduled_at ASC
                   LIMIT $1""",
                limit,
            )
            return [dict(r) for r in records]

    async def mark_show_n_sent_batch(self, schedule_ids: List[int]):
        """Помечает группу записей Показов N как отправленные одним запросом."""
        if not schedule_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_show_n_schedule SET sent_at = NOW() WHERE id = ANY($1::int[])",
                schedule_ids,
            )

    async def can_show_d(self, user_id: int, cooldown_minutes: int = 5) -> bool:
        query = """
            SELECT last_shown_at FROM user_last_show_d WHERE user_id = $1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, user_id)
            if not record:
                return True
            from datetime import datetime, timedelta
            last_shown = record['last_shown_at']
            return datetime.now(last_shown.tzinfo) - last_shown > timedelta(minutes=cooldown_minutes)

    async def mark_show_d_sent(self, user_id: int):
        query = """
            INSERT INTO user_last_show_d (user_id, last_shown_at)
            VALUES ($1, NOW())
            ON CONFLICT (user_id) DO UPDATE SET last_shown_at = NOW();
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)

    async def add_special_ad_button(self, text: str, url: str, show_in_feed: bool = True,
                                     show_in_profile: bool = True, show_in_referral: bool = False,
                                     show_in_purchase: bool = False, icon_emoji_id: str = None,
                                     button_style: str = 'primary'):
        query = """
            INSERT INTO special_ad_button (text, url, show_in_feed, show_in_profile, show_in_referral, show_in_purchase, icon_emoji_id, button_style)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, text, url, show_in_feed, show_in_profile, show_in_referral, show_in_purchase, icon_emoji_id, button_style)

    async def get_all_special_ad_buttons(self) -> List[Dict]:
        query = (
            "SELECT id, text, url, is_active, show_in_feed, show_in_profile, show_in_referral, show_in_purchase, icon_emoji_id, button_style "
            "FROM special_ad_button ORDER BY id DESC"
        )
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def get_active_special_ad_buttons(self) -> List[Dict]:
        """Все активные рекламные кнопки (для случайного выбора при показе)."""
        query = (
            "SELECT id, text, url, show_in_feed, show_in_profile, show_in_referral, show_in_purchase, icon_emoji_id, button_style "
            "FROM special_ad_button WHERE is_active = TRUE ORDER BY id"
        )
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

    async def delete_special_ad_button(self, button_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM special_ad_button WHERE id = $1", button_id)

    async def toggle_special_ad_button(self, button_id: int, is_active: bool):
        query = "UPDATE special_ad_button SET is_active = $1 WHERE id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, is_active, button_id)

    async def can_claim_daily_bonus(self, user_id: int) -> bool:
        query = "SELECT last_daily_bonus_at FROM users WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, user_id)
            if not record or not record['last_daily_bonus_at']:
                return True
            from datetime import datetime, timedelta
            last_bonus = record['last_daily_bonus_at']
            return datetime.now(last_bonus.tzinfo) - last_bonus > timedelta(hours=24)

    async def claim_daily_bonus(self, user_id: int, bonus_attempts: int = 2):
        query = """
            UPDATE users 
            SET attempts = attempts + $1, last_daily_bonus_at = NOW() 
            WHERE user_id = $2
            RETURNING attempts
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, bonus_attempts, user_id)

    async def check_session_attempts(self, user_id: int) -> int:
        """Возвращает количество использованных попыток в текущей сессии"""
        query = """
            SELECT session_attempts_used, session_reset_at FROM users WHERE user_id = $1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, user_id)
            if not record:
                return 0
            
            from datetime import datetime, timedelta
            if record['session_reset_at']:
                reset_at = record['session_reset_at']
                if datetime.now(reset_at.tzinfo) - reset_at > timedelta(hours=24):
                    await conn.execute("UPDATE users SET session_attempts_used = 0, session_reset_at = NOW() WHERE user_id = $1", user_id)
                    return 0
            
            return record['session_attempts_used'] or 0

    async def increment_session_attempts(self, user_id: int):
        query = """
            UPDATE users 
            SET session_attempts_used = COALESCE(session_attempts_used, 0) + 1,
                session_reset_at = COALESCE(session_reset_at, NOW())
            WHERE user_id = $1
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)

    async def set_selected_gift(self, user_id: int, gift: str):
        query = "UPDATE users SET selected_gift = $1 WHERE user_id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, gift, user_id)

    async def get_selected_gift(self, user_id: int) -> Optional[str]:
        query = "SELECT selected_gift FROM users WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, user_id)

    async def increment_tasks_completed(self, user_id: int):
        query = "UPDATE users SET total_tasks_completed = total_tasks_completed + 1 WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)

    async def increment_examples_solved(self, user_id: int):
        query = "UPDATE users SET total_examples_solved = total_examples_solved + 1 WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)

    async def get_total_tasks_completed(self) -> int:
        query = "SELECT SUM(total_tasks_completed) FROM users"
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(query)
            return count or 0

    async def get_total_examples_solved(self) -> int:
        query = "SELECT SUM(total_examples_solved) FROM users"
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(query)
            return count or 0

    async def get_first_op_passed_count(self, period: str = "total") -> int:
        async with self.pool.acquire() as conn:
            if period == "total":
                query = "SELECT count(*) FROM users WHERE has_passed_first_op = TRUE;"
            elif period == "today":
                query = "SELECT count(*) FROM users WHERE first_op_passed_at >= current_date;"
            elif period == "yesterday":
                query = "SELECT count(*) FROM users WHERE first_op_passed_at >= current_date - interval '1 day' AND first_op_passed_at < current_date;"
            elif period == "week":
                query = "SELECT count(*) FROM users WHERE first_op_passed_at >= current_date - interval '7 days';"
            else:
                return 0
            return await conn.fetchval(query)

    async def update_user_activity(self, user_id: int):
        query = "UPDATE users SET last_activity_at = NOW() WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id)


    async def get_all_service_settings(self) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM service_settings ORDER BY op1_priority")
            return [dict(r) for r in rows]

    async def get_service_settings(self, service: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM service_settings WHERE service = $1", service)
            return dict(row) if row else None

    async def update_service_field(self, service: str, field: str, value) -> None:
        allowed = {
            'op1_enabled', 'op1_max', 'op1_priority',
            'op2_enabled', 'op2_max', 'op2_priority',
            'tasks_enabled', 'tasks_max', 'tasks_priority', 'api_key',
        }
        if field not in allowed:
            raise ValueError(f"Unknown service_settings field: {field}")
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"UPDATE service_settings SET {field} = $1 WHERE service = $2",
                value, service,
            )

    async def get_services_for_op_stage(self, stage: int) -> list:
        """Включённые сервисы для этапа ОП, по приоритету."""
        enabled_col  = f"op{stage}_enabled"
        priority_col = f"op{stage}_priority"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM service_settings WHERE {enabled_col} = TRUE "
                f"ORDER BY {priority_col}",
            )
            return [dict(r) for r in rows]

    async def get_services_for_tasks(self) -> list:
        """Включённые сервисы для заданий, по приоритету."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM service_settings WHERE tasks_enabled = TRUE "
                "ORDER BY tasks_priority",
            )
            return [dict(r) for r in rows]


    async def get_op_stage_limit(self, stage: int) -> int:
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT max_total FROM op_stage_limits WHERE stage = $1", stage
            )
            return val if val is not None else 10

    async def set_op_stage_limit(self, stage: int, max_total: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO op_stage_limits (stage, max_total) VALUES ($1, $2) "
                "ON CONFLICT (stage) DO UPDATE SET max_total = EXCLUDED.max_total",
                stage, max_total,
            )


    async def get_setting_int(self, key: str, default: int) -> int:
        val = await self.get_setting(key)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default


    async def get_views_balance(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            val = await conn.fetchval("SELECT views_balance FROM users WHERE user_id = $1", user_id)
            return val or 0

    async def add_views_balance(self, user_id: int, amount: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE users SET views_balance = GREATEST(0, views_balance + $1) WHERE user_id = $2 RETURNING views_balance",
                amount, user_id,
            )

    async def add_author_reveal_balance(self, user_id: int, amount: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE users SET author_reveal_balance = GREATEST(0, author_reveal_balance + $1) WHERE user_id = $2 RETURNING author_reveal_balance",
                amount, user_id,
            )

    async def set_feed_gender(self, user_id: int, gender: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET feed_gender = $1 WHERE user_id = $2", gender, user_id)

    async def set_user_gender(self, user_id: int, gender: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET gender = $1 WHERE user_id = $2", gender, user_id)

    async def set_user_onboarded(self, user_id: int, value: bool = True):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET onboarded = $1 WHERE user_id = $2", value, user_id)

    async def is_user_banned(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1", user_id))

    async def set_user_banned(self, user_id: int, banned: bool):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = $1 WHERE user_id = $2", banned, user_id)

    async def set_hide_authorship(self, user_id: int, hide: bool):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET hide_authorship = $1 WHERE user_id = $2", hide, user_id)

    async def get_hide_authorship(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval("SELECT hide_authorship FROM users WHERE user_id = $1", user_id))

    async def add_stars_spent(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET stars_spent = stars_spent + $1 WHERE user_id = $2", amount, user_id)

    async def increment_referrals(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = $1", user_id)

    async def reset_op_counter(self, user_id: int, new_threshold: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET views_since_op = 0, next_op_threshold = $1 WHERE user_id = $2",
                new_threshold, user_id,
            )

    async def increment_op_counter(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE users SET views_since_op = views_since_op + 1 WHERE user_id = $1 RETURNING views_since_op",
                user_id,
            )


    async def add_circle(self, owner_id, file_id: str, is_bait: bool = False,
                         bait_order: int = None, fake_author_name: str = None,
                         fake_author_username: str = None, fake_author_url: str = None,
                         gender: str = 'any') -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO circles
                   (owner_id, file_id, is_bait, bait_order, fake_author_name,
                    fake_author_username, fake_author_url, gender)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                owner_id, file_id, is_bait, bait_order, fake_author_name,
                fake_author_username, fake_author_url, gender,
            )

    async def get_circle(self, circle_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM circles WHERE id = $1", circle_id)
            return dict(row) if row else None

    async def get_next_bait_circle(self, bait_index: int, feed_gender: str = 'any') -> Optional[Dict]:
        """Возвращает приманку №bait_index (0-based) по порядку bait_order с учётом ленты."""
        gender_clause = "" if feed_gender == 'any' else "AND (gender = $2 OR gender = 'any')"
        params = [bait_index] if feed_gender == 'any' else [bait_index, feed_gender]
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""SELECT * FROM circles
                   WHERE is_bait = TRUE AND is_active = TRUE AND is_blocked = FALSE
                   {gender_clause}
                   ORDER BY bait_order NULLS LAST, id
                   OFFSET $1 LIMIT 1""",
                *params,
            )
            return dict(row) if row else None

    async def count_active_bait(self, feed_gender: str = 'any') -> int:
        gender_clause = "" if feed_gender == 'any' else "AND (gender = $1 OR gender = 'any')"
        params = [] if feed_gender == 'any' else [feed_gender]
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                f"SELECT COUNT(*) FROM circles WHERE is_bait = TRUE AND is_active = TRUE AND is_blocked = FALSE {gender_clause}",
                *params,
            ) or 0

    async def get_random_unseen_circle(self, user_id: int, feed_gender: str = 'any') -> Optional[Dict]:
        """Случайный пользовательский (не-приманка) кружок, который юзер ещё не видел."""
        async with self.pool.acquire() as conn:
            gender_clause = "" if feed_gender == 'any' else "AND (c.gender = $2 OR c.gender = 'any')"
            params = [user_id] if feed_gender == 'any' else [user_id, feed_gender]
            row = await conn.fetchrow(
                f"""SELECT c.* FROM circles c
                    WHERE c.is_bait = FALSE AND c.is_active = TRUE AND c.is_blocked = FALSE
                      AND c.owner_id IS DISTINCT FROM $1
                      AND NOT EXISTS (SELECT 1 FROM circle_views v WHERE v.user_id = $1 AND v.circle_id = c.id)
                      {gender_clause}
                    ORDER BY RANDOM() LIMIT 1""",
                *params,
            )
            return dict(row) if row else None

    async def mark_circle_viewed(self, user_id: int, circle_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO circle_views (user_id, circle_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                user_id, circle_id,
            )
            await conn.execute("UPDATE circles SET views = views + 1 WHERE id = $1", circle_id)
            await conn.execute("UPDATE users SET circle_views_count = circle_views_count + 1 WHERE user_id = $1", user_id)

    async def set_circle_reaction(self, user_id: int, circle_id: int, reaction: str) -> Optional[str]:
        """Ставит/снимает реакцию. Возвращает итоговую реакцию (или None)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                cur = await conn.fetchval(
                    "SELECT reaction FROM circle_views WHERE user_id = $1 AND circle_id = $2",
                    user_id, circle_id,
                )
                await conn.execute(
                    "INSERT INTO circle_views (user_id, circle_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    user_id, circle_id,
                )
                new_val = None if cur == reaction else reaction
                await conn.execute(
                    "UPDATE circle_views SET reaction = $3 WHERE user_id = $1 AND circle_id = $2",
                    user_id, circle_id, new_val,
                )
                if cur == 'like':
                    await conn.execute("UPDATE circles SET likes = GREATEST(0, likes - 1) WHERE id = $1", circle_id)
                elif cur == 'dislike':
                    await conn.execute("UPDATE circles SET dislikes = GREATEST(0, dislikes - 1) WHERE id = $1", circle_id)
                if new_val == 'like':
                    await conn.execute("UPDATE circles SET likes = likes + 1 WHERE id = $1", circle_id)
                elif new_val == 'dislike':
                    await conn.execute("UPDATE circles SET dislikes = dislikes + 1 WHERE id = $1", circle_id)
                return new_val

    async def get_user_circles_stats(self, user_id: int) -> Dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT
                       COUNT(*) FILTER (WHERE is_active AND NOT is_blocked) AS in_feed,
                       COUNT(*) AS uploaded_total,
                       COALESCE(SUM(likes),0) AS likes,
                       COALESCE(SUM(dislikes),0) AS dislikes
                   FROM circles WHERE owner_id = $1""",
                user_id,
            )
            return dict(row) if row else {'in_feed': 0, 'uploaded_total': 0, 'likes': 0, 'dislikes': 0}

    async def get_best_circle(self, user_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM circles WHERE owner_id = $1 ORDER BY likes DESC, views DESC LIMIT 1",
                user_id,
            )
            return dict(row) if row else None

    async def get_top_circles(self, limit: int = 10) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.*, u.first_name AS owner_first_name, u.username AS owner_username
                   FROM circles c
                   LEFT JOIN users u ON u.user_id = c.owner_id
                   WHERE c.is_active AND NOT c.is_blocked AND c.is_bait = FALSE
                   ORDER BY c.likes DESC, c.views DESC LIMIT $1""",
                limit,
            )
            return [dict(r) for r in rows]


    async def has_revealed_author(self, user_id: int, circle_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval(
                "SELECT 1 FROM author_reveals WHERE user_id = $1 AND circle_id = $2",
                user_id, circle_id,
            ))

    async def add_author_reveal(self, user_id: int, circle_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO author_reveals (user_id, circle_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                user_id, circle_id,
            )
            await conn.execute("UPDATE users SET author_views_count = author_views_count + 1 WHERE user_id = $1", user_id)


    async def add_report(self, reporter_id: int, target_type: str,
                         target_circle_id: int = None, target_user_id: int = None,
                         reason: str = None) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO reports (reporter_id, target_type, target_circle_id, target_user_id, reason)
                   VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                reporter_id, target_type, target_circle_id, target_user_id, reason,
            )

    async def get_reports(self, status: str = 'open', limit: int = 20) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM reports WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status, limit,
            )
            return [dict(r) for r in rows]

    async def get_report(self, report_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM reports WHERE id = $1", report_id)
            return dict(row) if row else None

    async def resolve_report(self, report_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE reports SET status = 'resolved' WHERE id = $1", report_id)

    async def count_open_reports(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'open'") or 0

    async def block_circle(self, circle_id: int) -> Optional[int]:
        """Блокирует кружок. Возвращает owner_id (для уведомления автора) или None."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE circles SET is_blocked = TRUE WHERE id = $1 RETURNING owner_id", circle_id
            )


    async def get_bait_circles(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM circles WHERE is_bait = TRUE ORDER BY bait_order NULLS LAST, id"
            )
            return [dict(r) for r in rows]

    async def delete_circle(self, circle_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM circles WHERE id = $1", circle_id)

    async def get_own_circles(self, owner_id: int) -> List[Dict]:
        """Кружки, загруженные самим пользователем (не приманки), новые сверху."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM circles WHERE owner_id = $1 AND is_bait = FALSE AND is_blocked = FALSE "
                "ORDER BY created_at DESC, id DESC",
                owner_id,
            )
            return [dict(r) for r in rows]

    async def delete_own_circle(self, circle_id: int, owner_id: int) -> bool:
        """Удаляет кружок только если он принадлежит этому пользователю. True — если удалён."""
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM circles WHERE id = $1 AND owner_id = $2 AND is_bait = FALSE",
                circle_id, owner_id,
            )
            return res.endswith("1")


    async def count_uploads_today(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """SELECT CASE WHEN daily_uploads_date = CURRENT_DATE THEN daily_uploads ELSE 0 END
                   FROM users WHERE user_id = $1""",
                user_id,
            ) or 0

    async def register_upload(self, user_id: int):
        """Засчитывает один дневной аплоад (с авто-сбросом счётчика на новый день)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET
                       daily_uploads = CASE WHEN daily_uploads_date = CURRENT_DATE THEN daily_uploads + 1 ELSE 1 END,
                       daily_uploads_date = CURRENT_DATE
                   WHERE user_id = $1""",
                user_id,
            )

    async def add_extra_upload_credits(self, user_id: int, amount: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE users SET extra_upload_credits = GREATEST(0, extra_upload_credits + $1) WHERE user_id = $2 RETURNING extra_upload_credits",
                amount, user_id,
            )

    async def use_extra_upload_credit(self, user_id: int) -> bool:
        """Списывает один платный слот атомарно. True — если был и списан."""
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(
                "UPDATE users SET extra_upload_credits = extra_upload_credits - 1 WHERE user_id = $1 AND extra_upload_credits > 0 RETURNING extra_upload_credits",
                user_id,
            )
            return val is not None

    async def next_bait_order(self) -> int:
        async with self.pool.acquire() as conn:
            val = await conn.fetchval("SELECT COALESCE(MAX(bait_order), 0) + 1 FROM circles WHERE is_bait = TRUE")
            return val or 1


    async def add_bait_message(self, text: str, button_text: str = 'Посмотреть',
                               delay_min: int = 30, delay_max: int = 90) -> int:
        if delay_max < delay_min:
            delay_min, delay_max = delay_max, delay_min
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO bait_messages (text, button_text, delay_min, delay_max) VALUES ($1,$2,$3,$4) RETURNING id",
                text, button_text, delay_min, delay_max,
            )

    async def get_bait_messages(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM bait_messages ORDER BY id")
            return [dict(r) for r in rows]

    async def get_active_bait_messages(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM bait_messages WHERE is_active = TRUE")
            return [dict(r) for r in rows]

    async def delete_bait_message(self, bait_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM bait_messages WHERE id = $1", bait_id)

    async def sync_bait_schedules(self, grace_minutes: int = 1, limit: int = 200) -> int:
        """
        Создаёт/перевыставляет расписание байтов для неактивных пользователей,
        у которых ещё нет расписания под их ТЕКУЩУЮ активность (anchor).
        Каждому посту — своё случайное время last_activity + random(delay_min..delay_max).
        Новая активность меняет last_activity → расписание перевыставляется (sent=FALSE).
        """
        query = """
            WITH eligible AS (
                SELECT u.user_id, u.last_activity_at AS anchor
                FROM users u
                WHERE u.is_banned = FALSE
                  AND u.last_activity_at IS NOT NULL
                  AND u.last_activity_at < NOW() - ($1 * INTERVAL '1 minute')
                  AND NOT EXISTS (
                      SELECT 1 FROM user_bait_schedule s
                      WHERE s.user_id = u.user_id AND s.anchor = u.last_activity_at
                  )
                LIMIT $2
            )
            INSERT INTO user_bait_schedule (user_id, bait_id, fire_at, anchor, sent)
            SELECT e.user_id, b.id,
                   e.anchor + ((b.delay_min
                       + floor(random() * (GREATEST(b.delay_max, b.delay_min) - b.delay_min + 1)))::int)
                       * INTERVAL '1 minute',
                   e.anchor, FALSE
            FROM eligible e
            CROSS JOIN bait_messages b
            WHERE b.is_active = TRUE
            ON CONFLICT (user_id, bait_id)
            DO UPDATE SET fire_at = EXCLUDED.fire_at, anchor = EXCLUDED.anchor, sent = FALSE
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, grace_minutes, limit)
            try:
                return int(result.split()[-1])
            except Exception:
                return 0

    async def get_due_baits(self, limit: int = 100) -> List[Dict]:
        """
        Созревшие байты: время пришло, ещё не отправлены, и пользователь НЕ
        возвращался после планирования (last_activity_at <= anchor).
        """
        query = """
            SELECT s.user_id, s.bait_id, b.text, b.button_text
            FROM user_bait_schedule s
            JOIN bait_messages b ON b.id = s.bait_id AND b.is_active = TRUE
            JOIN users u ON u.user_id = s.user_id
            WHERE s.sent = FALSE
              AND s.fire_at <= NOW()
              AND u.is_banned = FALSE
              AND u.last_activity_at <= s.anchor
            ORDER BY s.fire_at ASC
            LIMIT $1
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
            return [dict(r) for r in rows]

    async def mark_bait_schedule_sent(self, user_id: int, bait_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_bait_schedule SET sent = TRUE WHERE user_id = $1 AND bait_id = $2",
                user_id, bait_id,
            )


    async def log_star_payment(self, user_id: int, amount: int, kind: str,
                               payload: str = None, charge_id: str = None) -> bool:
        """Логирует платёж. Возвращает False, если этот charge_id уже был
        (повторная доставка апдейта) — тогда начислять второй раз нельзя."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO star_payments (user_id, amount, kind, payload, charge_id)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (charge_id) DO NOTHING
                   RETURNING id""",
                user_id, amount, kind, payload, charge_id,
            )
            return row is not None

    async def get_purchase_stats(self) -> Dict[str, Dict[str, int]]:
        """Покупки за звёзды по типам: {kind: {'count': n, 'stars': сумма}}."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT kind, COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS stars FROM star_payments GROUP BY kind"
            )
            return {r['kind']: {'count': r['cnt'], 'stars': r['stars']} for r in rows}

    async def get_total_referrals(self) -> int:
        """Сколько всего пользователей пришло по чьим-то реф-ссылкам."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id IS NOT NULL") or 0

    async def get_total_author_reveals(self) -> int:
        """Сколько всего раскрытий авторов сделано (из таблицы раскрытий)."""
        async with self.pool.acquire() as conn:
            try:
                return await conn.fetchval("SELECT COUNT(*) FROM author_reveals") or 0
            except Exception:
                return 0

    async def get_stars_stats(self, period: str = "total") -> int:
        async with self.pool.acquire() as conn:
            if period == "total":
                q = "SELECT COALESCE(SUM(amount),0) FROM star_payments;"
            elif period == "today":
                q = "SELECT COALESCE(SUM(amount),0) FROM star_payments WHERE created_at >= current_date;"
            elif period == "yesterday":
                q = "SELECT COALESCE(SUM(amount),0) FROM star_payments WHERE created_at >= current_date - interval '1 day' AND created_at < current_date;"
            elif period == "week":
                q = "SELECT COALESCE(SUM(amount),0) FROM star_payments WHERE created_at >= current_date - interval '7 days';"
            else:
                return 0
            return await conn.fetchval(q) or 0

    async def get_stars_by_day(self, days: int = 14) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT date_trunc('day', created_at)::date AS day, COALESCE(SUM(amount),0) AS total
                   FROM star_payments
                   WHERE created_at >= current_date - ($1 || ' days')::interval
                   GROUP BY day ORDER BY day""",
                str(days),
            )
            return [dict(r) for r in rows]

    async def get_users_by_day(self, days: int = 14) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT date_trunc('day', created_at)::date AS day, COUNT(*) AS total
                   FROM users
                   WHERE created_at >= current_date - ($1 || ' days')::interval
                   GROUP BY day ORDER BY day""",
                str(days),
            )
            return [dict(r) for r in rows]

    async def get_circles_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM circles WHERE is_bait = FALSE AND is_active AND NOT is_blocked"
            ) or 0

    async def get_total_circle_views(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COALESCE(SUM(views),0) FROM circles") or 0


    async def set_anon_profile(self, user_id: int, gender: str, age: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET anon_gender = $1, anon_age = $2 WHERE user_id = $3",
                gender, age, user_id,
            )

    async def set_last_anon_partner(self, user_id: int, partner_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_anon_partner = $2 WHERE user_id = $1",
                user_id, partner_id,
            )

    async def get_last_anon_partner(self, user_id: int) -> Optional[int]:
        async with self.pool.acquire() as conn:
            val = await conn.fetchval("SELECT last_anon_partner FROM users WHERE user_id = $1", user_id)
            return val

    async def anon_dequeue(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM anon_queue WHERE user_id = $1", user_id)

    async def anon_is_searching(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval("SELECT 1 FROM anon_queue WHERE user_id = $1", user_id))

    async def anon_match_or_enqueue(self, user_id: int, gender: str, age: int) -> Optional[int]:
        """
        Пытается найти ожидающего собеседника. Если найден — создаёт пару и
        возвращает его id. Иначе ставит пользователя в очередь и возвращает None.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                partner = await conn.fetchrow(
                    """SELECT user_id FROM anon_queue
                       WHERE user_id <> $1
                       ORDER BY created_at
                       FOR UPDATE SKIP LOCKED
                       LIMIT 1""",
                    user_id,
                )
                if partner:
                    pid = partner['user_id']
                    await conn.execute("DELETE FROM anon_queue WHERE user_id = ANY($1::bigint[])", [user_id, pid])
                    await conn.execute(
                        "INSERT INTO anon_pairs (user_a, user_b) VALUES ($1, $2)", user_id, pid)
                    return pid
                await conn.execute(
                    """INSERT INTO anon_queue (user_id, gender, age) VALUES ($1,$2,$3)
                       ON CONFLICT (user_id) DO UPDATE SET gender = EXCLUDED.gender,
                       age = EXCLUDED.age, created_at = NOW()""",
                    user_id, gender, age,
                )
                return None

    async def anon_get_partner(self, user_id: int) -> Optional[int]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT user_a, user_b FROM anon_pairs
                   WHERE active = TRUE AND (user_a = $1 OR user_b = $1)
                   ORDER BY id DESC LIMIT 1""",
                user_id,
            )
            if not row:
                return None
            return row['user_b'] if row['user_a'] == user_id else row['user_a']

    async def anon_end_pair(self, user_id: int) -> Optional[int]:
        """Завершает активную пару пользователя. Возвращает id собеседника."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """SELECT id, user_a, user_b FROM anon_pairs
                       WHERE active = TRUE AND (user_a = $1 OR user_b = $1)
                       ORDER BY id DESC LIMIT 1 FOR UPDATE""",
                    user_id,
                )
                if not row:
                    return None
                await conn.execute("UPDATE anon_pairs SET active = FALSE WHERE id = $1", row['id'])
                return row['user_b'] if row['user_a'] == user_id else row['user_a']

    async def get_anon_active_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM anon_pairs WHERE active = TRUE") or 0

    async def get_anon_queue_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM anon_queue") or 0