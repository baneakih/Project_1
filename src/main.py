import os
import time
import threading
from datetime import datetime

import pytz
import telebot
from dotenv import load_dotenv
from telebot import types

from utils import (
    add_smart_task,
    delete_task_permanently,
    delete_all_tasks_permanently,
    get_all_active_tasks,
    get_task_details,
    init_db,
    toggle_task_status_by_id,
    toggle_user_task_status,
    get_global_active_reminders,
    parse_task_with_ai,
)

load_dotenv()
init_db()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(BOT_TOKEN)

user_creation_data = {}
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


def check_reminders():
    """Фоновый поток для проверки напоминаний всех пользователей."""
    while True:
        try:
            now_msk = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")
            tasks = get_global_active_reminders()

            for task_id, user_id, title, remind_date, description in tasks:
                if remind_date and remind_date.strip() == now_msk:
                    desc_text = f"\n📄 Описание: {description}" if description else ""

                    try:
                        bot.send_message(
                            user_id,
                            f"⏰ НАПОМИНАНИЕ О ЗАДАЧЕ!\n\n"
                            f"📌 {title}"
                            f"{desc_text}\n\n"
                            f"Не забудьте выполнить её!",
                        )
                    except Exception as send_error:
                        print(
                            f"Не удалось отправить уведомление пользователю {user_id}: {send_error}"
                        )

                    toggle_task_status_by_id(task_id)

            time.sleep(30)

        except Exception as e:
            print(f"Ошибка в фоновом таймере: {e}")
            time.sleep(10)


def make_main_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)

    btn_list = types.InlineKeyboardButton(
        "🗂 Показать все задачи", callback_data="go_to_list"
    )
    btn_fast = types.InlineKeyboardButton(
        "⚡ Быстрая задача", callback_data="create_fast"
    )
    btn_smart = types.InlineKeyboardButton(
        "⏰ Умная задача", callback_data="create_smart"
    )

    markup.add(btn_list)
    markup.row(btn_fast, btn_smart)

    return markup


def make_tasks_keyboard(user_id: int):
    """Создает список задач конкретного пользователя."""
    markup = types.InlineKeyboardMarkup()
    tasks = get_all_active_tasks(user_id)

    if not tasks:
        markup.add(
            types.InlineKeyboardButton("🎉 Все дела сделаны!", callback_data="none")
        )
    else:
        for task_id, title, remind_date in tasks:
            date_str = f" (⏰ {remind_date})" if remind_date else ""

            btn_view = types.InlineKeyboardButton(
                f"📌 {title}{date_str}", callback_data=f"view_{task_id}"
            )
            btn_del = types.InlineKeyboardButton(
                "🗑", callback_data=f"listdelete_{task_id}"
            )

            markup.row(btn_view, btn_del)

        markup.add(
            types.InlineKeyboardButton(
                "🚨 Удалить все мои задачи",
                callback_data="confirm_delete_all",
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад в главное меню", callback_data="go_to_main"
        )
    )

    return markup


@bot.message_handler(commands=["start", "list"])
def show_dashboard(message):
    bot.send_message(
        message.chat.id,
        "🧠 Ваш умный многопользовательский планер:\n\n"
        "Вы можете просто написать обычным текстом, например:\n"
        "«Напомни купить подарок завтра в 14:00»\n\n"
        "ИИ автоматически попробует создать задачу.\n\n"
        "Либо управляйте через панель действий ниже:",
        reply_markup=make_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "create_fast")
def start_fast_task(call):
    chat_id = call.message.chat.id

    msg = bot.send_message(
        chat_id,
        "⚡ Введите название быстрой задачи. Она создастся мгновенно:",
    )

    bot.register_next_step_handler(msg, process_fast_task_title)
    bot.answer_callback_query(call.id)


def process_fast_task_title(message):
    chat_id = message.chat.id
    title_text = message.text if message.text else "Без названия"

    response = add_smart_task(
        user_id=chat_id,
        title=title_text,
        description=None,
        remind_date=None,
    )

    bot.send_message(chat_id, response, reply_markup=make_main_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "none")
def handle_none_button(call):
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "create_smart")
def start_smart_task(call):
    chat_id = call.message.chat.id
    user_creation_data[chat_id] = {}

    msg = bot.send_message(
        chat_id,
        "📝 [Шаг 1/3] Введите заголовок задачи:",
    )

    bot.register_next_step_handler(msg, process_smart_title)
    bot.answer_callback_query(call.id)


def process_smart_title(message):
    chat_id = message.chat.id

    if chat_id not in user_creation_data:
        user_creation_data[chat_id] = {}

    user_creation_data[chat_id]["title"] = (
        message.text if message.text else "Без названия"
    )

    msg = bot.send_message(
        chat_id,
        "📄 [Шаг 2/3] Введите описание или напишите: пропустить",
    )

    bot.register_next_step_handler(msg, process_smart_description)


def process_smart_description(message):
    chat_id = message.chat.id
    desc_text = message.text if message.text else ""

    if desc_text.lower() == "пропустить":
        user_creation_data[chat_id]["description"] = None
    else:
        user_creation_data[chat_id]["description"] = desc_text

    msg = bot.send_message(
        chat_id,
        "⏰ [Шаг 3/3] Введите дату и время по МСК в формате:\n"
        "ДД.ММ.ГГГГ ЧЧ:ММ\n\n"
        "Например: 22.06.2026 18:30\n\n"
        "Или напишите: пропустить",
    )

    bot.register_next_step_handler(msg, process_smart_date)


def process_smart_date(message):
    chat_id = message.chat.id
    date_text = message.text if message.text else ""

    remind_date = None if date_text.lower() == "пропустить" else date_text

    data = user_creation_data.get(chat_id)

    if not data:
        bot.send_message(
            chat_id,
            "⚠️ Не удалось найти данные создаваемой задачи. Попробуйте заново.",
            reply_markup=make_main_keyboard(),
        )
        return

    response = add_smart_task(
        user_id=chat_id,
        title=data["title"],
        description=data.get("description"),
        remind_date=remind_date,
    )

    bot.send_message(chat_id, response, reply_markup=make_main_keyboard())
    user_creation_data.pop(chat_id, None)


@bot.callback_query_handler(func=lambda call: call.data.startswith("view_"))
def view_task_details_handler(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    task = get_task_details(chat_id, task_id)

    if not task:
        bot.answer_callback_query(call.id, "Задача не найдена или доступ ограничен!")
        return

    _, title, description, remind_date, status = task

    desc_text = description if description else "Описание отсутствует"
    date_text = f"{remind_date} по МСК" if remind_date else "Не указано"

    info_msg = (
        f"📋 Задача: {title}\n\n"
        f"📄 Описание: {desc_text}\n"
        f"⏰ Напоминание: {date_text}\n"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "✅ Отметить выполненной", callback_data=f"complete_{task_id}"
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

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text=info_msg,
        reply_markup=markup,
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("complete_"))
def handle_complete(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    toggle_user_task_status(chat_id, task_id)

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🎉 Отлично! Задача выполнена и убрана из активных.",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Выполнено!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def handle_delete(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    delete_task_permanently(chat_id, task_id)

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🗑 Задача полностью удалена.",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Удалено!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("listdelete_"))
def handle_list_delete(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    delete_task_permanently(chat_id, task_id)

    bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=call.message.id,
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Задача удалена!")


@bot.callback_query_handler(func=lambda call: call.data == "confirm_delete_all")
def ask_for_delete_all(call):
    markup = types.InlineKeyboardMarkup()

    btn_yes = types.InlineKeyboardButton(
        "💥 ДА, УДАЛИТЬ ВСЁ", callback_data="execute_delete_all"
    )
    btn_no = types.InlineKeyboardButton("❌ Отмена", callback_data="go_to_list")

    markup.row(btn_yes, btn_no)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        text=(
            "⚠️ ВНИМАНИЕ!\n\n"
            "Вы уверены, что хотите удалить все свои активные задачи "
            "без возможности восстановления?"
        ),
        reply_markup=markup,
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "execute_delete_all")
def execute_clear_database(call):
    chat_id = call.message.chat.id

    delete_all_tasks_permanently(chat_id)

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🚨 Ваш личный список очищен. Все ваши задачи удалены.",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Задачи удалены!")


@bot.callback_query_handler(func=lambda call: call.data == "go_to_list")
def handle_to_list(call):
    chat_id = call.message.chat.id

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🗂 Ваш список активных задач:",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "go_to_main")
def handle_to_main(call):
    chat_id = call.message.chat.id

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text="🧠 Ваш персональный планер:\nВыберите действие ниже:",
        reply_markup=make_main_keyboard(),
    )

    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: True, content_types=["text"])
def ai_message_handler(message):
    chat_id = message.chat.id

    status_msg = bot.send_message(
        chat_id,
        "🤖 Секунду, ИИ разбирает задачу...",
    )

    ai_result = parse_task_with_ai(message.text)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if "error" in ai_result:
        print(f"AI ERROR: {ai_result['error']}")

        add_smart_task(
            user_id=chat_id,
            title=message.text,
            description=None,
            remind_date=None,
        )

        bot.send_message(
            chat_id,
            "⚠️ Не удалось подключить ИИ для разбора фразы.\n"
            "Задача сохранена в стандартном режиме, только как заголовок.",
            reply_markup=make_main_keyboard(),
        )
        return

    title = ai_result.get("title")
    description = ai_result.get("description")
    remind_date = ai_result.get("remind_date")

    if not title:
        bot.send_message(
            chat_id,
            "❌ Не удалось распознать суть задачи. Попробуйте написать иначе.",
            reply_markup=make_main_keyboard(),
        )
        return

    add_smart_task(
        user_id=chat_id,
        title=title,
        description=description,
        remind_date=remind_date,
    )

    success_msg = f"✨ ИИ успешно добавил задачу!\n\n" f"📌 Заголовок: {title}\n"

    if description:
        success_msg += f"📄 Описание: {description}\n"

    if remind_date:
        success_msg += f"⏰ Напоминание: {remind_date} МСК\n"
    else:
        success_msg += "⏰ Напоминание: не назначено\n"

    bot.send_message(
        chat_id,
        success_msg,
        reply_markup=make_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: True)
def global_callback_catcher(call):
    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка callback: {e}")


if __name__ == "__main__":
    reminder_thread = threading.Thread(target=check_reminders, daemon=True)
    reminder_thread.start()

    print("Многопользовательский планер с ИИ успешно запущен...")

    bot.infinity_polling(skip_pending=True)
