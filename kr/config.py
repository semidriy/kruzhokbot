import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BANNER_GIF_ID = "https://t.me/poststatsb/4"
SUBGRAM_API_KEY = os.getenv("SUBGRAM_API_KEY")
BOTOHUB_API_KEY = os.getenv("BOTOHUB_API_KEY")

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

ADMIN_CHANNEL_ID = -1002804747517
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id]

SPECIAL_BUTTON_URL = os.getenv("SPECIAL_BUTTON_URL")
SPECIAL_BUTTON_TEXT = os.getenv("SPECIAL_BUTTON_TEXT", "💫 Забрать подарок 🎉")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "astaninec")

KRUZHOK_DEFAULTS = {
    "free_initial_views":        "10",
    "ref_reward_views":          "5",
    "ref_reward_author_views":   "3",
    "op_min_interval":           "7",
    "op_max_interval":           "10",
    "author_reveal_cost":        "40",
    "bait_delay_minutes":        "40",
    "record_reward_views":       "3",
}
