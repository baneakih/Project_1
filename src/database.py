import os
import sqlite3
from datetime import datetime, timedelta

from utils import DATE_FORMAT, get_now_msk, normalize_remind_date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "todo.db")


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
        cursor.execute(
            "DELETE FROM smart_tasks WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def get_global_active_reminders():
    """Возвращает только задачи с неотправленным уведомлением."""
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

        cursor.execute(
            "SELECT COUNT(*) FROM smart_tasks WHERE user_id = ?",
            (user_id,),
        )
        total = cursor.fetchone()[0]

    return {
        "active": active,
        "completed": completed,
        "total": total,
    }
