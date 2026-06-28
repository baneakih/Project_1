import os
import time
import threading
from datetime import timedelta

import telebot
from dotenv import load_dotenv
from telebot import types
from config import TASK_WORDS

from database import (
    add_smart_task,
    delete_all_tasks_permanently,
    delete_task_permanently,
    get_all_active_tasks,
    get_global_active_reminders,
    get_task_details,
    get_tasks_for_day,
    get_user_stats,
    init_db,
    mark_reminder_sent,
    snooze_task,
    toggle_user_task_status,
)

from ai import parse_task_with_ai

from utils import (
    get_now_msk,
    is_valid_remind_date,
    normalize_remind_date,
)

from keyboards import (
    make_main_keyboard,
    make_reminder_keyboard,
    make_tasks_keyboard,
    format_task_created,
)

load_dotenv()
init_db()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=8)
user_creation_data: dict[int, dict] = {}


# ---------- Helpers ----------
def answer_callback(call, text: str | None = None) -> None:
    try:
        bot.answer_callback_query(call.id, text=text)
    except Exception as e:
        print(f"Ошибка answer_callback_query: {e}")


def safe_edit_message_text(
    chat_id: int, message_id: int, text: str, reply_markup=None
) -> None:
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
    except Exception as e:
        error_text = str(e).lower()
        if "message is not modified" not in error_text:
            print(f"Ошибка edit_message_text: {e}")


def safe_edit_message_reply_markup(
    chat_id: int, message_id: int, reply_markup=None
) -> None:
    try:
        bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    except Exception as e:
        error_text = str(e).lower()
        if "message is not modified" not in error_text:
            print(f"Ошибка edit_message_reply_markup: {e}")


def is_cancel_text(message) -> bool:
    return bool(
        message.text and message.text.strip().lower() in ["/cancel", "отмена", "cancel"]
    )


def is_task_like(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(word in lowered for word in TASK_WORDS)


def get_tasks_keyboard(user_id: int):
    tasks = get_all_active_tasks(user_id)
    return make_tasks_keyboard(tasks)


# ---------- Reminders ----------
def check_reminders():
    while True:
        try:
            now_msk = get_now_msk().strftime("%d.%m.%Y %H:%M")
            tasks = get_global_active_reminders()

            for task_id, user_id, title, description, remind_date in tasks:
                if not remind_date or remind_date.strip() != now_msk:
                    continue

                desc_text = f"\n📄 Описание: {description}" if description else ""
                msg = (
                    f"⏰ НАПОМИНАНИЕ!\n\n"
                    f"📌 {title}"
                    f"{desc_text}\n\n"
                    f"Задача не закрыта автоматически. Отметьте её выполненной, когда закончите."
                )

                try:
                    bot.send_message(
                        user_id,
                        msg,
                        reply_markup=make_reminder_keyboard(task_id),
                    )
                    mark_reminder_sent(task_id)
                except Exception as send_error:
                    print(
                        f"Не удалось отправить уведомление пользователю {user_id}: {send_error}"
                    )

            time.sleep(30)
        except Exception as e:
            print(f"Ошибка в фоновом таймере: {e}")
            time.sleep(10)


# ---------- Commands ----------
@bot.message_handler(commands=["start"])
def show_dashboard(message):
    bot.send_message(
        message.chat.id,
        "🧠 Maritaro AI Planner\n\n"
        "Я умный Telegram-планер с ИИ.\n\n"
        "Пример:\n"
        "«Напомни завтра в 14:00 купить молоко»\n\n"
        "Команды:\n"
        "/help — помощь\n"
        "/today — задачи на сегодня\n"
        "/tomorrow — задачи на завтра\n"
        "/stats — статистика\n"
        "/cancel — отменить сценарий",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(commands=["help"])
def help_handler(message):
    bot.send_message(
        message.chat.id,
        "🤖 Как пользоваться Maritaro\n\n"
        "Просто напишите задачу обычным языком:\n"
        "• Напомни завтра в 14:00 купить молоко\n"
        "• Через 2 часа созвон с клиентом\n"
        "• В пятницу в 18:00 тренировка\n\n"
        "Команды:\n"
        "/today — задачи на сегодня\n"
        "/tomorrow — задачи на завтра\n"
        "/stats — статистика\n"
        "/cancel — отменить текущий сценарий",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(commands=["cancel"])
def cancel_handler(message):
    chat_id = message.chat.id
    user_creation_data.pop(chat_id, None)
    bot.send_message(
        chat_id, "Текущий сценарий отменён.", reply_markup=make_main_keyboard()
    )


@bot.message_handler(commands=["today"])
def today_handler(message):
    send_day_tasks(message.chat.id, get_now_msk(), "📅 Задачи на сегодня")


@bot.message_handler(commands=["tomorrow"])
def tomorrow_handler(message):
    send_day_tasks(
        message.chat.id,
        get_now_msk() + timedelta(days=1),
        "🌅 Задачи на завтра",
    )


@bot.message_handler(commands=["stats"])
def stats_handler(message):
    stats = get_user_stats(message.chat.id)
    bot.send_message(
        message.chat.id,
        "📊 Статистика\n\n"
        f"Активных задач: {stats['active']}\n"
        f"Выполнено: {stats['completed']}\n"
        f"Всего создано: {stats['total']}",
        reply_markup=make_main_keyboard(),
    )


def send_day_tasks(chat_id: int, day, title: str):
    tasks = get_tasks_for_day(chat_id, day)
    if not tasks:
        bot.send_message(
            chat_id, f"{title}\n\n🎉 Задач нет.", reply_markup=make_main_keyboard()
        )
        return

    text = f"{title}\n\n"
    for _, task_title, remind_date in tasks:
        time_part = remind_date.split(" ")[1] if remind_date else "без времени"
        text += f"• {time_part} — {task_title}\n"

    bot.send_message(chat_id, text, reply_markup=make_main_keyboard())


# ---------- Callbacks ----------
@bot.callback_query_handler(func=lambda call: call.data == "today")
def today_callback(call):
    answer_callback(call)
    send_day_tasks(call.message.chat.id, get_now_msk(), "📅 Задачи на сегодня")


@bot.callback_query_handler(func=lambda call: call.data == "tomorrow")
def tomorrow_callback(call):
    answer_callback(call)
    send_day_tasks(
        call.message.chat.id, get_now_msk() + timedelta(days=1), "🌅 Задачи на завтра"
    )


@bot.callback_query_handler(func=lambda call: call.data == "create_fast")
def start_fast_task(call):
    answer_callback(call)
    chat_id = call.message.chat.id
    msg = bot.send_message(
        chat_id,
        "⚡ Введите название быстрой задачи.\n\nЧтобы отменить, напишите: отмена",
    )
    bot.register_next_step_handler(msg, process_fast_task_title)


def process_fast_task_title(message):
    chat_id = message.chat.id
    if is_cancel_text(message):
        bot.send_message(
            chat_id, "Создание задачи отменено.", reply_markup=make_main_keyboard()
        )
        return

    title_text = message.text if message.text else "Без названия"
    add_smart_task(
        user_id=chat_id, title=title_text, description=None, remind_date=None
    )
    bot.send_message(
        chat_id,
        format_task_created(title_text, None, None),
        reply_markup=make_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "create_smart")
def start_smart_task(call):
    answer_callback(call)
    chat_id = call.message.chat.id
    user_creation_data[chat_id] = {}
    msg = bot.send_message(
        chat_id,
        "📝 [Шаг 1/3] Введите заголовок задачи.\n\nЧтобы отменить, напишите: отмена",
    )
    bot.register_next_step_handler(msg, process_smart_title)


def process_smart_title(message):
    chat_id = message.chat.id
    if is_cancel_text(message):
        user_creation_data.pop(chat_id, None)
        bot.send_message(
            chat_id, "Создание задачи отменено.", reply_markup=make_main_keyboard()
        )
        return

    user_creation_data.setdefault(chat_id, {})
    user_creation_data[chat_id]["title"] = (
        message.text if message.text else "Без названия"
    )
    msg = bot.send_message(
        chat_id, "📄 [Шаг 2/3] Введите описание или напишите: пропустить"
    )
    bot.register_next_step_handler(msg, process_smart_description)


def process_smart_description(message):
    chat_id = message.chat.id
    if is_cancel_text(message):
        user_creation_data.pop(chat_id, None)
        bot.send_message(
            chat_id, "Создание задачи отменено.", reply_markup=make_main_keyboard()
        )
        return

    desc_text = message.text if message.text else ""
    user_creation_data[chat_id]["description"] = (
        None if desc_text.lower() == "пропустить" else desc_text
    )

    msg = bot.send_message(
        chat_id,
        "⏰ [Шаг 3/3] Введите дату и время по МСК:\n"
        "ДД.ММ.ГГГГ ЧЧ:ММ\n\n"
        "Например: 22.06.2026 18:30\n\n"
        "Или напишите: пропустить",
    )
    bot.register_next_step_handler(msg, process_smart_date)


def process_smart_date(message):
    chat_id = message.chat.id
    if is_cancel_text(message):
        user_creation_data.pop(chat_id, None)
        bot.send_message(
            chat_id, "Создание задачи отменено.", reply_markup=make_main_keyboard()
        )
        return

    date_text = message.text if message.text else ""
    remind_date = (
        None if date_text.lower() == "пропустить" else normalize_remind_date(date_text)
    )

    if date_text.lower() != "пропустить" and not remind_date:
        msg = bot.send_message(
            chat_id,
            "❌ Неверный формат даты.\n\nВведите так: 22.06.2026 18:30\nИли напишите: пропустить",
        )
        bot.register_next_step_handler(msg, process_smart_date)
        return

    data = user_creation_data.get(chat_id)
    if not data:
        bot.send_message(
            chat_id,
            "⚠️ Не удалось найти данные создаваемой задачи. Попробуйте заново.",
            reply_markup=make_main_keyboard(),
        )
        return

    title = data["title"]
    description = data.get("description")
    add_smart_task(
        user_id=chat_id, title=title, description=description, remind_date=remind_date
    )
    bot.send_message(
        chat_id,
        format_task_created(title, description, remind_date),
        reply_markup=make_main_keyboard(),
    )
    user_creation_data.pop(chat_id, None)


@bot.callback_query_handler(func=lambda call: call.data == "none")
def handle_none_button(call):
    answer_callback(call)


@bot.callback_query_handler(func=lambda call: call.data == "go_to_list")
def handle_to_list(call):
    answer_callback(call)
    chat_id = call.message.chat.id
    safe_edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🗂 Ваш список активных задач:",
        reply_markup=get_tasks_keyboard(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data == "go_to_main")
def handle_to_main(call):
    answer_callback(call)
    safe_edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        text="🧠 Maritaro AI Planner\nВыберите действие:",
        reply_markup=make_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("view_"))
def view_task_details_handler(call):
    answer_callback(call)
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])
    task = get_task_details(chat_id, task_id)

    if not task:
        answer_callback(call, "Задача не найдена или доступ ограничен!")
        return

    _, title, description, remind_date, status, reminder_sent = task
    desc_text = description if description else "Описание отсутствует"
    date_text = f"{remind_date} по МСК" if remind_date else "Не указано"
    remind_status = "Да" if reminder_sent else "Нет"

    info_msg = (
        f"📋 Задача: {title}\n\n"
        f"📄 Описание: {desc_text}\n"
        f"⏰ Напоминание: {date_text}\n"
        f"🔔 Уведомление отправлено: {remind_status}\n"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "✅ Отметить выполненной", callback_data=f"complete_{task_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "⏰ Напомнить через 15 минут", callback_data=f"snooze15_{task_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Полностью удалить", callback_data=f"delete_{task_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад к списку задач", callback_data="go_to_list"
        )
    )

    safe_edit_message_text(chat_id, call.message.id, info_msg, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("complete_"))
def handle_complete(call):
    answer_callback(call, "Выполнено!")
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])
    toggle_user_task_status(chat_id, task_id)
    safe_edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🎉 Отлично! Задача выполнена.",
        reply_markup=get_tasks_keyboard(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("snooze15_"))
def handle_snooze_15(call):
    answer_callback(call, "Напоминание перенесено")
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])
    new_time = snooze_task(chat_id, task_id, 15)
    safe_edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text=f"⏰ Хорошо, напомню ещё раз в {new_time} МСК.",
        reply_markup=get_tasks_keyboard(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("snooze60_"))
def handle_snooze_60(call):
    answer_callback(call, "Напоминание перенесено")
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])
    new_time = snooze_task(chat_id, task_id, 60)
    safe_edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text=f"⏰ Хорошо, напомню ещё раз в {new_time} МСК.",
        reply_markup=get_tasks_keyboard(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def handle_delete(call):
    answer_callback(call, "Удалено!")
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])
    delete_task_permanently(chat_id, task_id)
    safe_edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🗑 Задача полностью удалена.",
        reply_markup=get_tasks_keyboard(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("listdelete_"))
def handle_list_delete(call):
    answer_callback(call, "Задача удалена!")
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])
    delete_task_permanently(chat_id, task_id)
    safe_edit_message_reply_markup(
        chat_id=chat_id,
        message_id=call.message.id,
        reply_markup=get_tasks_keyboard(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data == "confirm_delete_all")
def ask_for_delete_all(call):
    answer_callback(call)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(
            "💥 ДА, УДАЛИТЬ ВСЁ", callback_data="execute_delete_all"
        ),
        types.InlineKeyboardButton("❌ Отмена", callback_data="go_to_list"),
    )
    safe_edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        text=(
            "⚠️ ВНИМАНИЕ!\n\n"
            "Вы уверены, что хотите удалить все свои активные задачи без возможности восстановления?"
        ),
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data == "execute_delete_all")
def execute_clear_database(call):
    answer_callback(call, "Задачи удалены!")
    chat_id = call.message.chat.id
    delete_all_tasks_permanently(chat_id)
    safe_edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🚨 Ваш личный список очищен. Все ваши задачи удалены.",
        reply_markup=get_tasks_keyboard(chat_id),
    )


# ---------- Voice / AI text ----------
@bot.message_handler(content_types=["voice"])
def voice_handler(message):
    bot.send_message(
        message.chat.id,
        "🎤 Голосовые команды скоро появятся. Пока напишите задачу текстом.",
        reply_markup=make_main_keyboard(),
    )


def process_ai_task_async(
    chat_id: int, text: str, status_message_id: int | None = None
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
        user_id=chat_id, title=title, description=description, remind_date=remind_date
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
        bot.send_message(chat_id, "Отменено.", reply_markup=make_main_keyboard())
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

    status_msg = bot.send_message(chat_id, "🤖 Секунду, ИИ разбирает задачу...")
    threading.Thread(
        target=process_ai_task_async,
        args=(chat_id, text, status_msg.message_id),
        daemon=True,
    ).start()


@bot.callback_query_handler(func=lambda call: True)
def global_callback_catcher(call):
    answer_callback(call)


if __name__ == "__main__":
    reminder_thread = threading.Thread(target=check_reminders, daemon=True)
    reminder_thread.start()
    print("Maritaro AI Planner запущен.")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
