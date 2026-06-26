import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

import pytz
import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

DB_PATH = os.path.join(BASE_DIR, "todo.db")
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


# ---------- SQLite ----------
def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_column(
    cursor: sqlite3.Cursor, table_name: str, column_name: str, column_type: str
) -> None:
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


def init_db() -> None:
    """Создаёт/обновляет таблицу задач. Шифрование удалено, данные хранятся в обычных полях."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS smart_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                remind_date TEXT,
                status INTEGER DEFAULT 0,
                reminder_sent INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )

        _ensure_column(cursor, "smart_tasks", "description", "TEXT")
        _ensure_column(cursor, "smart_tasks", "remind_date", "TEXT")
        _ensure_column(cursor, "smart_tasks", "status", "INTEGER DEFAULT 0")
        _ensure_column(cursor, "smart_tasks", "reminder_sent", "INTEGER DEFAULT 0")
        _ensure_column(cursor, "smart_tasks", "created_at", "TEXT")

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_user_status
            ON smart_tasks(user_id, status)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_reminders
            ON smart_tasks(status, reminder_sent, remind_date)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_user_day
            ON smart_tasks(user_id, remind_date)
            """
        )

        conn.commit()


# ---------- Tasks ----------
def add_smart_task(
    user_id: int,
    title: str,
    description: str | None = None,
    remind_date: str | None = None,
) -> str:
    title = (title or "Без названия").strip()
    description = (
        description.strip()
        if isinstance(description, str) and description.strip()
        else None
    )
    remind_date = normalize_remind_date(remind_date)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO smart_tasks (
                user_id, title, description, remind_date,
                status, reminder_sent, created_at
            )
            VALUES (?, ?, ?, ?, 0, 0, ?)
            """,
            (
                user_id,
                title,
                description,
                remind_date,
                get_now_msk().strftime(DATE_FORMAT),
            ),
        )
        conn.commit()

    return f"🚀 Задача «{title}» успешно создана!"


def get_all_active_tasks(user_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, remind_date
            FROM smart_tasks
            WHERE user_id = ? AND status = 0
            ORDER BY
                CASE WHEN remind_date IS NULL OR remind_date = '' THEN 1 ELSE 0 END,
                remind_date ASC,
                id DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()


def get_tasks_for_day(user_id: int, day: datetime):
    day_prefix = day.strftime("%d.%m.%Y")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, remind_date
            FROM smart_tasks
            WHERE user_id = ?
              AND status = 0
              AND remind_date LIKE ?
            ORDER BY remind_date ASC, id ASC
            """,
            (user_id, f"{day_prefix}%"),
        )
        return cursor.fetchall()


def get_task_details(user_id: int, task_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_date, status, reminder_sent
            FROM smart_tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        return cursor.fetchone()


def toggle_user_task_status(user_id: int, task_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE smart_tasks
            SET status = 1
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        conn.commit()


def mark_reminder_sent(task_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE smart_tasks
            SET reminder_sent = 1
            WHERE id = ?
            """,
            (task_id,),
        )
        conn.commit()


def snooze_task(user_id: int, task_id: int, minutes: int) -> str:
    new_time = get_now_msk() + timedelta(minutes=minutes)
    new_time_str = new_time.strftime(DATE_FORMAT)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE smart_tasks
            SET remind_date = ?, reminder_sent = 0
            WHERE id = ? AND user_id = ?
            """,
            (new_time_str, task_id, user_id),
        )
        conn.commit()

    return new_time_str


def delete_task_permanently(user_id: int, task_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM smart_tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        conn.commit()


def delete_all_tasks_permanently(user_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM smart_tasks WHERE user_id = ?", (user_id,))
        conn.commit()


def get_global_active_reminders():
    """Возвращает только задачи с ненаправленным уведомлением."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, title, description, remind_date
            FROM smart_tasks
            WHERE status = 0
              AND reminder_sent = 0
              AND remind_date IS NOT NULL
              AND remind_date != ''
            """
        )
        return cursor.fetchall()


def get_user_stats(user_id: int) -> dict[str, int]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM smart_tasks WHERE user_id = ? AND status = 0",
            (user_id,),
        )
        active = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM smart_tasks WHERE user_id = ? AND status = 1",
            (user_id,),
        )
        completed = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM smart_tasks WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()[0]

    return {"active": active, "completed": completed, "total": total}


# ---------- AI ----------
def parse_task_with_ai(user_text: str):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {"error": "OPENROUTER_API_KEY не найден в .env"}

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    now_msk = get_now_msk()
    system_prompt = (
        "Ты — ИИ-модуль Telegram-планировщика задач. "
        "Извлеки из сообщения пользователя JSON с полями: title, description, remind_date. "
        "title — короткий заголовок задачи. "
        "description — дополнительное описание или null. "
        "remind_date — дата и время напоминания строго в формате DD.MM.YYYY HH:MM или null. "
        "Если пользователь пишет 'завтра', 'сегодня', 'через 30 минут', 'через 2 часа', "
        "вычисли точную дату относительно текущего времени. "
        "Если текст не является задачей или напоминанием, верни title=null. "
        "Ответь только валидным JSON без markdown и без пояснений."
    )

    models = [
        "deepseek/deepseek-chat-v3-0324",
        "openai/gpt-oss-20b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ]

    last_error = None
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Текущее время по Москве: {now_msk.strftime(DATE_FORMAT)}. "
                        f"Текст пользователя: {user_text}"
                    ),
                },
            ],
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code != 200:
                last_error = (
                    f"Ошибка OpenRouter API {response.status_code}: {response.text}"
                )
                continue

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                last_error = f"ИИ не вернул JSON: {content}"
                continue

            parsed = json.loads(match.group(0))
            remind_date = normalize_remind_date(parsed.get("remind_date"))
            return {
                "title": parsed.get("title"),
                "description": parsed.get("description"),
                "remind_date": remind_date,
            }
        except Exception as e:
            last_error = f"Ошибка парсинга или сети: {str(e)}"
            continue

    return {"error": last_error or "Не удалось получить ответ от ИИ"}
