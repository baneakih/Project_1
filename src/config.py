import os

import pytz
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

load_dotenv(os.path.join(PROJECT_DIR, ".env"))

DB_PATH = os.path.join(BASE_DIR, "todo.db")

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
DATE_FORMAT = "%d.%m.%Y %H:%M"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_MODELS = [
    "deepseek/deepseek-chat-v3-0324",
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

TASK_WORDS = [
    "напомни",
    "напомнить",
    "завтра",
    "сегодня",
    "послезавтра",
    "через",
    "купить",
    "сделать",
    "позвонить",
    "созвон",
    "встреча",
    "задача",
    "дедлайн",
    "запланируй",
    "запиши",
    "не забыть",
    "надо",
    "нужно",
]
