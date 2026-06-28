import os
from datetime import datetime

import pytz
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
DATE_FORMAT = "%d.%m.%Y %H:%M"


# ---------- Time / validation ----------
def get_now_msk() -> datetime:
    return datetime.now(MOSCOW_TZ)


def normalize_remind_date(value: str | None) -> str | None:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = datetime.strptime(value, DATE_FORMAT)
        return parsed.strftime(DATE_FORMAT)
    except ValueError:
        return None


def is_valid_remind_date(value: str | None) -> bool:
    return value is None or normalize_remind_date(value) is not None
