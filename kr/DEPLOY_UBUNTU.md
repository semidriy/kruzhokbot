# Установка KruzhokBot на чистую Ubuntu

Гайд с нуля: пустой сервер Ubuntu (20.04 / 22.04 / 24.04). Код заливается по SFTP.
Все команды — от `root` (или через `sudo`).

---

## 0. Важно перед заливкой по SFTP

- **НЕ заливай папку `venv/`** с Windows — она не работает на Linux. Создадим новую на сервере.
- Папки `__pycache__`, `.idea` тоже не нужны (необязательно, но мусор).
- Файл `.env` залей (или создадим его на сервере на шаге 4).

Заливай содержимое проекта по SFTP в папку **`/opt/kruzhokbot`**.

---

## 1. Обновить систему и поставить пакеты

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib
```

Проверить, что Python есть:

```bash
python3 --version
```

---

## 2. Запустить PostgreSQL и создать базу

PostgreSQL после установки запускается сам. Включаем автозапуск:

```bash
systemctl enable --now postgresql
```

Создаём пользователя БД и базу (имя/пароль/база — `krug`, как в `.env`):

```bash
sudo -u postgres psql -c "CREATE USER krug WITH PASSWORD 'krug';"
sudo -u postgres psql -c "CREATE DATABASE krug OWNER krug;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE krug TO krug;"
```

> Таблицы создавать руками НЕ нужно — бот создаёт их сам при первом запуске.

Проверить подключение (введёт пароль `krug`):

```bash
psql "postgresql://krug:krug@localhost:5432/krug" -c "\conninfo"
```

---

## 3. Залить код и создать виртуальное окружение

Создаём папку (если ещё не залил туда по SFTP):

```bash
mkdir -p /opt/kruzhokbot
cd /opt/kruzhokbot
```

> Сюда по SFTP должны лежать `bot.py`, `requirements.txt`, папки `handlers/`, `database/` и т.д.

Создаём окружение и ставим зависимости:

```bash
cd /opt/kruzhokbot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Настроить `.env`

Если `.env` не залил — создай его:

```bash
nano /opt/kruzhokbot/.env
```

Содержимое (подставь свой токен и ID админов):

```env
BOT_TOKEN=сюда_токен_бота
ADMIN_IDS=111111111,222222222
ADMIN_USERNAME=ondorix

DB_USER=krug
DB_PASSWORD=krug
DB_HOST=localhost
DB_PORT=5432
DB_NAME=krug

SUBGRAM_API_KEY=
BOTOHUB_API_KEY=
SPECIAL_BUTTON_URL=
SPECIAL_BUTTON_TEXT=
```

Сохранить в nano: `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## 5. Тестовый запуск (проверить, что всё ок)

```bash
cd /opt/kruzhokbot
source venv/bin/activate
python bot.py
```

Должно появиться:

```
Инициализация таблиц базы данных завершена.
Успешное подключение к базе данных PostgreSQL.
Starting bot...
Run polling for bot @...
```

Если так — всё работает. Останови: `Ctrl+C`.

> Если ошибка подключения к БД — проверь шаг 2 и пароль в `.env`.

---

## 6. Запуск как сервис (systemd, автозапуск + авто-рестарт)

Создаём отдельного пользователя для бота (безопаснее, чем root):

```bash
useradd -r -s /usr/sbin/nologin kruzhok
chown -R kruzhok:kruzhok /opt/kruzhokbot
```

Создаём unit-файл:

```bash
nano /etc/systemd/system/kruzhokbot.service
```

Вставить:

```ini
[Unit]
Description=KruzhokBot (Telegram)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=kruzhok
WorkingDirectory=/opt/kruzhokbot
ExecStart=/opt/kruzhokbot/venv/bin/python /opt/kruzhokbot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Включаем и запускаем:

```bash
systemctl daemon-reload
systemctl enable --now kruzhokbot
systemctl status kruzhokbot
```

---

## 7. Логи и управление

```bash
journalctl -u kruzhokbot -f          # live-логи
systemctl restart kruzhokbot         # перезапуск
systemctl stop kruzhokbot            # остановить
systemctl start kruzhokbot           # запустить
```

---

## ⚠️ Важно: только ОДИН экземпляр бота

Telegram отдаёт обновления только одному поллеру на токен. Если запустить бота
дважды (например, сервис + руками `python bot.py`) — они будут конфликтовать и
обработка ломается. Когда работает systemd-сервис — **не запускай `python bot.py`
руками**.

## Обновление кода (когда зальёшь новую версию по SFTP)

```bash
systemctl stop kruzhokbot
# залить новые файлы по SFTP в /opt/kruzhokbot
cd /opt/kruzhokbot
source venv/bin/activate
pip install -r requirements.txt        # если менялись зависимости
chown -R kruzhok:kruzhok /opt/kruzhokbot
systemctl start kruzhokbot
```

## Примечание про цветные кнопки

Цветные inline-кнопки и премиум-эмодзи на кнопках работают только на кастомном
(пропатченном) Bot API сервере. На обычном `api.telegram.org` бот работает, но
такие кнопки рисуются обычными. Это не мешает запуску.
