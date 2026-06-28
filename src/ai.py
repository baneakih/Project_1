import json
import os
import re

import requests

from config import DATE_FORMAT, OPENROUTER_MODELS, OPENROUTER_URL
from utils import get_now_msk, normalize_remind_date


def parse_task_with_ai(user_text: str):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {"error": "OPENROUTER_API_KEY не найден в .env"}

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

    last_error = None

    for model in OPENROUTER_MODELS:
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
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=15,
            )

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
