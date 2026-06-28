import threading

from ai import parse_task_with_ai
from callbacks import is_cancel_text
from config import TASK_WORDS
from database import add_smart_task
from keyboards import format_task_created, make_main_keyboard
from utils import is_valid_remind_date


def is_task_like(text: str) -> bool:
    if not text:
        return False

    lowered = text.lower()
    return any(word in lowered for word in TASK_WORDS)


def register_message_handlers(bot, user_creation_data: dict[int, dict]):
    @bot.message_handler(content_types=["voice"])
    def voice_handler(message):
        bot.send_message(
            message.chat.id,
            "🎤 Голосовые команды скоро появятся. Пока напишите задачу текстом.",
            reply_markup=make_main_keyboard(),
        )

    def process_ai_task_async(
        chat_id: int,
        text: str,
        status_message_id: int | None = None,
    ):
        ai_result = parse_task_with_ai(text)

        if status_message_id:
            try:
                bot.delete_message(chat_id, status_message_id)
            except Exception:
                pass

        if "error" in ai_result:
            print(f"AI ERROR: {ai_result['error']}")
            bot.send_message(
                chat_id,
                "⚠️ ИИ временно недоступен.\n\n"
                "Задача не была создана автоматически. Используйте кнопку «Быстрая задача» или попробуйте позже.",
                reply_markup=make_main_keyboard(),
            )
            return

        title = ai_result.get("title")
        description = ai_result.get("description")
        remind_date = ai_result.get("remind_date")

        if not title:
            bot.send_message(
                chat_id,
                "❌ Я не понял задачу.\n\nПопробуйте так:\n«Напомни завтра в 14:00 купить молоко»",
                reply_markup=make_main_keyboard(),
            )
            return

        if remind_date and not is_valid_remind_date(remind_date):
            remind_date = None

        add_smart_task(
            user_id=chat_id,
            title=title,
            description=description,
            remind_date=remind_date,
        )

        bot.send_message(
            chat_id,
            format_task_created(title, description, remind_date),
            reply_markup=make_main_keyboard(),
        )

    @bot.message_handler(func=lambda message: True, content_types=["text"])
    def ai_message_handler(message):
        chat_id = message.chat.id
        text = message.text or ""

        if is_cancel_text(message):
            user_creation_data.pop(chat_id, None)
            bot.send_message(
                chat_id,
                "Отменено.",
                reply_markup=make_main_keyboard(),
            )
            return

        if not is_task_like(text):
            bot.send_message(
                chat_id,
                "🤖 Я планировщик задач.\n\n"
                "Напишите задачу, например:\n"
                "«Напомни завтра в 14:00 купить молоко»\n\n"
                "Или используйте кнопки ниже.",
                reply_markup=make_main_keyboard(),
            )
            return

        status_msg = bot.send_message(
            chat_id,
            "🤖 Секунду, ИИ разбирает задачу...",
        )

        threading.Thread(
            target=process_ai_task_async,
            args=(chat_id, text, status_msg.message_id),
            daemon=True,
        ).start()
