from datetime import datetime

from config import DATE_FORMAT, MOSCOW_TZ


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
