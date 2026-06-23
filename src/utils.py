import os
import sqlite3
import requests
import json
import re
import base64
from datetime import datetime, timedelta

import pytz
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

load_dotenv(os.path.join(PROJECT_DIR, ".env"))

DB_PATH = os.path.join(BASE_DIR, "todo.db")
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

DATE_FORMAT = "%d.%m.%Y %H:%M"


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
    if not value:
        return True

    return normalize_remind_date(value) is not None


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS smart_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                remind_date TEXT,
                status INTEGER DEFAULT 0,
                title_enc TEXT,
                description_enc TEXT,
                is_encrypted INTEGER DEFAULT 0,
                reminder_sent INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_security (
                user_id INTEGER PRIMARY KEY,
                salt TEXT NOT NULL,
                pin_check TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        _ensure_column(cursor, "smart_tasks", "title_enc", "TEXT")
        _ensure_column(cursor, "smart_tasks", "description_enc", "TEXT")
        _ensure_column(cursor, "smart_tasks", "is_encrypted", "INTEGER DEFAULT 0")
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

        conn.commit()


def _ensure_column(cursor, table_name: str, column_name: str, column_type: str):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


def _derive_key(pin: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )

    return base64.urlsafe_b64encode(kdf.derive(pin.encode("utf-8")))


def _fernet_from_key(key: bytes) -> Fernet:
    return Fernet(key)


def encrypt_text(text: str | None, key: bytes | None) -> str | None:
    if text is None:
        return None

    if key is None:
        return None

    fernet = _fernet_from_key(key)
    return fernet.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_text(token: str | None, key: bytes | None) -> str | None:
    if not token:
        return None

    if key is None:
        return "🔒 Зашифровано"

    try:
        fernet = _fernet_from_key(key)
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return "🔒 Неверный PIN"


def user_has_pin(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_security WHERE user_id = ?",
            (user_id,),
        )
        return cursor.fetchone() is not None


def set_user_pin(user_id: int, pin: str) -> bytes:
    salt = os.urandom(16)
    key = _derive_key(pin, salt)
    fernet = _fernet_from_key(key)
    pin_check = fernet.encrypt(b"ok").decode("utf-8")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO user_security (user_id, salt, pin_check, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                base64.b64encode(salt).decode("utf-8"),
                pin_check,
                get_now_msk().strftime(DATE_FORMAT),
            ),
        )
        conn.commit()

    encrypt_existing_user_tasks(user_id, key)
    return key


def unlock_user(user_id: int, pin: str) -> bytes | None:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT salt, pin_check
            FROM user_security
            WHERE user_id = ?
            """,
            (user_id,),
        )

        row = cursor.fetchone()

    if not row:
        return None

    salt_b64, pin_check = row
    salt = base64.b64decode(salt_b64)
    key = _derive_key(pin, salt)

    try:
        fernet = _fernet_from_key(key)
        value = fernet.decrypt(pin_check.encode("utf-8")).decode("utf-8")
        if value == "ok":
            return key
    except InvalidToken:
        return None

    return None


def encrypt_existing_user_tasks(user_id: int, key: bytes):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, title, description
            FROM smart_tasks
            WHERE user_id = ?
              AND COALESCE(is_encrypted, 0) = 0
            """,
            (user_id,),
        )

        rows = cursor.fetchall()

        for task_id, title, description in rows:
            title_enc = encrypt_text(title, key)
            description_enc = encrypt_text(description, key)

            cursor.execute(
                """
                UPDATE smart_tasks
                SET title_enc = ?,
                    description_enc = ?,
                    title = ?,
                    description = NULL,
                    is_encrypted = 1
                WHERE id = ? AND user_id = ?
                """,
                (
                    title_enc,
                    description_enc,
                    "🔒 encrypted",
                    task_id,
                    user_id,
                ),
            )

        conn.commit()


def add_smart_task(
    user_id: int,
    title: str,
    description: str = None,
    remind_date: str = None,
    encryption_key: bytes | None = None,
):
    title = (title or "Без названия").strip()
    description = description.strip() if isinstance(description, str) else description
    remind_date = normalize_remind_date(remind_date)

    is_encrypted = 1 if encryption_key else 0

    if encryption_key:
        title_enc = encrypt_text(title, encryption_key)
        description_enc = encrypt_text(description, encryption_key)
        stored_title = "🔒 encrypted"
        stored_description = None
    else:
        title_enc = None
        description_enc = None
        stored_title = title
        stored_description = description

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO smart_tasks (
                user_id,
                title,
                description,
                remind_date,
                status,
                title_enc,
                description_enc,
                is_encrypted,
                reminder_sent,
                created_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, 0, ?)
            """,
            (
                user_id,
                stored_title,
                stored_description,
                remind_date,
                title_enc,
                description_enc,
                is_encrypted,
                get_now_msk().strftime(DATE_FORMAT),
            ),
        )
        conn.commit()

    return f"🚀 Задача «{title}» успешно создана!"


def _decode_task_title(row, encryption_key: bytes | None):
    (
        task_id,
        title,
        description,
        remind_date,
        status,
        title_enc,
        description_enc,
        is_encrypted,
        reminder_sent,
    ) = row

    if is_encrypted:
        title = decrypt_text(title_enc, encryption_key)

    return task_id, title, remind_date


def get_all_active_tasks(user_id: int, encryption_key: bytes | None = None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_date, status,
                   title_enc, description_enc, is_encrypted, reminder_sent
            FROM smart_tasks
            WHERE user_id = ? AND status = 0
            ORDER BY
                CASE
                    WHEN remind_date IS NULL OR remind_date = '' THEN 1
                    ELSE 0
                END,
                remind_date ASC,
                id DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()

    return [_decode_task_title(row, encryption_key) for row in rows]


def get_tasks_for_day(
    user_id: int,
    day: datetime,
    encryption_key: bytes | None = None,
):
    day_prefix = day.strftime("%d.%m.%Y")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_date, status,
                   title_enc, description_enc, is_encrypted, reminder_sent
            FROM smart_tasks
            WHERE user_id = ?
              AND status = 0
              AND remind_date LIKE ?
            ORDER BY remind_date ASC
            """,
            (user_id, f"{day_prefix}%"),
        )
        rows = cursor.fetchall()

    return [_decode_task_title(row, encryption_key) for row in rows]


def get_task_details(user_id: int, task_id: int, encryption_key: bytes | None = None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_date, status,
                   title_enc, description_enc, is_encrypted, reminder_sent
            FROM smart_tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        row = cursor.fetchone()

    if not row:
        return None

    (
        task_id,
        title,
        description,
        remind_date,
        status,
        title_enc,
        description_enc,
        is_encrypted,
        reminder_sent,
    ) = row

    if is_encrypted:
        title = decrypt_text(title_enc, encryption_key)
        description = decrypt_text(description_enc, encryption_key)

    return task_id, title, description, remind_date, status, reminder_sent


def toggle_user_task_status(user_id: int, task_id: int):
    with sqlite3.connect(DB_PATH) as conn:
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


def mark_reminder_sent(task_id: int):
    with sqlite3.connect(DB_PATH) as conn:
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


def snooze_task(user_id: int, task_id: int, minutes: int):
    new_time = get_now_msk() + timedelta(minutes=minutes)
    new_time_str = new_time.strftime(DATE_FORMAT)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE smart_tasks
            SET remind_date = ?,
                reminder_sent = 0
            WHERE id = ? AND user_id = ?
            """,
            (new_time_str, task_id, user_id),
        )
        conn.commit()

    return new_time_str


def delete_task_permanently(user_id: int, task_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM smart_tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        conn.commit()


def delete_all_tasks_permanently(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM smart_tasks
            WHERE user_id = ?
            """,
            (user_id,),
        )
        conn.commit()


def get_global_active_reminders():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, title, description, remind_date,
                   title_enc, description_enc, is_encrypted
            FROM smart_tasks
            WHERE status = 0
              AND reminder_sent = 0
              AND remind_date IS NOT NULL
              AND remind_date != ''
            """
        )
        return cursor.fetchall()


def get_user_stats(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM smart_tasks
            WHERE user_id = ? AND status = 0
            """,
            (user_id,),
        )
        active = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM smart_tasks
            WHERE user_id = ? AND status = 1
            """,
            (user_id,),
        )
        completed = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM smart_tasks
            WHERE user_id = ?
            """,
            (user_id,),
        )
        total = cursor.fetchone()[0]

    return {
        "active": active,
        "completed": completed,
        "total": total,
    }


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
        data = {
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
            response = requests.post(url, headers=headers, json=data, timeout=30)

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
