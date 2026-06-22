import os
import sqlite3
import requests
import json
import re
from datetime import datetime
import pytz
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

load_dotenv(os.path.join(PROJECT_DIR, ".env"))

DB_PATH = os.path.join(BASE_DIR, "todo.db")
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


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
                status INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()


def add_smart_task(
    user_id: int, title: str, description: str = None, remind_date: str = None
):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO smart_tasks (user_id, title, description, remind_date, status)
            VALUES (?, ?, ?, ?, 0)
            """,
            (user_id, title, description, remind_date),
        )
        conn.commit()

    return f"🚀 Задача «{title}» успешно создана!"


def get_all_active_tasks(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, remind_date
            FROM smart_tasks
            WHERE user_id = ? AND status = 0
            ORDER BY id DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()


def get_global_active_reminders():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, title, remind_date, description
            FROM smart_tasks
            WHERE status = 0
              AND remind_date IS NOT NULL
              AND remind_date != ''
            """
        )
        return cursor.fetchall()


def get_task_details(user_id: int, task_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_date, status
            FROM smart_tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        return cursor.fetchone()


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


def toggle_task_status_by_id(task_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE smart_tasks
            SET status = 1
            WHERE id = ?
            """,
            (task_id,),
        )
        conn.commit()


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


def parse_task_with_ai(user_text: str):
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return {"error": "OPENROUTER_API_KEY не найден в .env"}

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    now_msk = datetime.now(MOSCOW_TZ)

    system_prompt = (
        "Ты — ИИ-модуль Telegram-планировщика задач. "
        "Извлеки из сообщения пользователя JSON с полями: title, description, remind_date. "
        "title — короткий заголовок задачи. "
        "description — дополнительное описание или null. "
        "remind_date — дата и время напоминания строго в формате DD.MM.YYYY HH:MM или null. "
        "Если пользователь пишет 'завтра', 'сегодня', 'через 30 минут', 'через 2 часа', "
        "вычисли точную дату относительно текущего времени. "
        "Ответь только валидным JSON без markdown и без пояснений."
    )

    data = {
        "model": "deepseek/deepseek-chat-v3-0324",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Текущее время по Москве: {now_msk.strftime('%d.%m.%Y %H:%M')}. "
                    f"Текст пользователя: {user_text}"
                ),
            },
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)

        if response.status_code != 200:
            return {
                "error": f"Ошибка OpenRouter API {response.status_code}: {response.text}"
            }

        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)

        if not match:
            return {"error": f"ИИ не вернул JSON: {content}"}

        parsed = json.loads(match.group(0))

        return {
            "title": parsed.get("title"),
            "description": parsed.get("description"),
            "remind_date": parsed.get("remind_date"),
        }

    except Exception as e:
        return {"error": f"Ошибка парсинга или сети: {str(e)}"}
