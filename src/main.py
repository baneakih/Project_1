import os
import time
import threading
from datetime import timedelta

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
    get_tasks_for_day,
    get_user_stats,
    init_db,
    toggle_user_task_status,
    get_global_active_reminders,
    parse_task_with_ai,
    user_has_pin,
    set_user_pin,
    unlock_user,
    encrypt_existing_user_tasks,
    mark_reminder_sent,
    snooze_task,
    decrypt_text,
    get_now_msk,
    is_valid_remind_date,
    normalize_remind_date,
)

load_dotenv()
init_db()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=8)

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

user_creation_data = {}
user_pin_flow = {}
UNLOCKED_KEYS = {}

TASK_WORDS = [
    "напомни",
    "напомнить",
    "завтра",
    "сегодня",
    "послезавтра",
    "через",
    "купить",
    "сделать",
    "позвонить",
    "созвон",
    "встреча",
    "задача",
    "дедлайн",
    "запланируй",
    "запиши",
    "не забыть",
    "надо",
    "нужно",
]


def get_user_key(user_id: int):
    return UNLOCKED_KEYS.get(user_id)


def is_cancel_text(message) -> bool:
    return bool(
        message.text and message.text.strip().lower() in ["/cancel", "отмена", "cancel"]
    )


def is_task_like(text: str) -> bool:
    if not text:
        return False

    lowered = text.lower()
    return any(word in lowered for word in TASK_WORDS)


def make_main_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)

    markup.add(
        types.InlineKeyboardButton(
            "🗂 Показать все задачи",
            callback_data="go_to_list",
        )
    )

    markup.row(
        types.InlineKeyboardButton(
            "⚡ Быстрая задача",
            callback_data="create_fast",
        ),
        types.InlineKeyboardButton(
            "⏰ Умная задача",
            callback_data="create_smart",
        ),
    )

    markup.row(
        types.InlineKeyboardButton(
            "📅 Сегодня",
            callback_data="today",
        ),
        types.InlineKeyboardButton(
            "🌅 Завтра",
            callback_data="tomorrow",
        ),
    )

    return markup


def make_tasks_keyboard(user_id: int):
    markup = types.InlineKeyboardMarkup()
    tasks = get_all_active_tasks(user_id, get_user_key(user_id))

    if not tasks:
        markup.add(
            types.InlineKeyboardButton(
                "🎉 Все дела сделаны!",
                callback_data="none",
            )
        )
    else:
        for task_id, title, remind_date in tasks:
            date_str = f" (⏰ {remind_date})" if remind_date else ""

            markup.row(
                types.InlineKeyboardButton(
                    f"📌 {title}{date_str}",
                    callback_data=f"view_{task_id}",
                ),
                types.InlineKeyboardButton(
                    "🗑",
                    callback_data=f"listdelete_{task_id}",
                ),
            )

        markup.add(
            types.InlineKeyboardButton(
                "🚨 Удалить все мои задачи",
                callback_data="confirm_delete_all",
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад в главное меню",
            callback_data="go_to_main",
        )
    )

    return markup


def make_reminder_keyboard(task_id: int):
    markup = types.InlineKeyboardMarkup()

    markup.row(
        types.InlineKeyboardButton(
            "✅ Выполнено",
            callback_data=f"complete_{task_id}",
        ),
        types.InlineKeyboardButton(
            "⏰ +15 мин",
            callback_data=f"snooze15_{task_id}",
        ),
    )

    markup.add(
        types.InlineKeyboardButton(
            "⏰ +1 час",
            callback_data=f"snooze60_{task_id}",
        )
    )

    return markup


def format_task_created(title: str, description: str | None, remind_date: str | None):
    text = f"✅ Задача создана\n\n📌 {title}\n"

    if description:
        text += f"📄 {description}\n"

    if remind_date:
        text += f"⏰ {remind_date} МСК\n"
    else:
        text += "⏰ Без напоминания\n"

    text += "\n🔒 Если включён PIN, текст задачи хранится зашифрованным."

    return text


def check_reminders():
    while True:
        try:
            now_msk = get_now_msk().strftime("%d.%m.%Y %H:%M")
            tasks = get_global_active_reminders()

            for (
                task_id,
                user_id,
                title,
                description,
                remind_date,
                title_enc,
                description_enc,
                is_encrypted,
            ) in tasks:
                if not remind_date or remind_date.strip() != now_msk:
                    continue

                key = get_user_key(user_id)

                if is_encrypted:
                    safe_title = decrypt_text(title_enc, key)
                    safe_description = decrypt_text(description_enc, key)
                else:
                    safe_title = title
                    safe_description = description

                if is_encrypted and key is None:
                    msg = (
                        "⏰ У вас есть запланированное напоминание.\n\n"
                        "🔒 Текст задачи зашифрован.\n"
                        "Введите /unlock, чтобы открыть детали."
                    )
                else:
                    desc_text = (
                        f"\n📄 Описание: {safe_description}"
                        if safe_description and not safe_description.startswith("🔒")
                        else ""
                    )

                    msg = (
                        f"⏰ НАПОМИНАНИЕ!\n\n"
                        f"📌 {safe_title}"
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


@bot.message_handler(commands=["start"])
def show_dashboard(message):
    user_id = message.chat.id

    privacy_status = (
        "🔒 PIN включён. Используйте /unlock после перезапуска бота."
        if user_has_pin(user_id)
        else "🔓 PIN ещё не настроен. Используйте /setpin для приватного режима."
    )

    bot.send_message(
        user_id,
        "🧠 Maritaro AI Planner\n\n"
        "Я умный Telegram-планер с ИИ.\n\n"
        "Пример:\n"
        "«Напомни завтра в 14:00 купить молоко»\n\n"
        f"{privacy_status}\n\n"
        "Команды:\n"
        "/help — помощь\n"
        "/today — задачи на сегодня\n"
        "/tomorrow — задачи на завтра\n"
        "/stats — статистика\n"
        "/privacy — приватность",
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
        "/setpin — включить шифрование\n"
        "/unlock — открыть зашифрованные задачи\n"
        "/lock — закрыть доступ\n"
        "/cancel — отменить текущий сценарий",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(commands=["privacy"])
def privacy_handler(message):
    bot.send_message(
        message.chat.id,
        "🔒 Приватность\n\n"
        "Если включить PIN через /setpin, названия и описания задач будут храниться в базе зашифрованными.\n\n"
        "Важно:\n"
        "• user_id, статус и дата напоминания остаются открытыми, чтобы бот мог работать.\n"
        "• текст задач без PIN прочитать нельзя.\n"
        "• после перезапуска бота нужно снова ввести /unlock.\n"
        "• если PIN потерян, расшифровать задачи невозможно.",
    )


@bot.message_handler(commands=["setpin"])
def setpin_start(message):
    chat_id = message.chat.id

    msg = bot.send_message(
        chat_id,
        "🔐 Придумайте PIN для шифрования задач.\n\n"
        "Минимум 4 символа.\n"
        "Чтобы отменить, напишите: отмена",
    )

    user_pin_flow[chat_id] = "setpin"
    bot.register_next_step_handler(msg, process_setpin)


def process_setpin(message):
    chat_id = message.chat.id

    if is_cancel_text(message):
        user_pin_flow.pop(chat_id, None)
        bot.send_message(chat_id, "Отменено.", reply_markup=make_main_keyboard())
        return

    pin = message.text.strip() if message.text else ""

    if len(pin) < 4:
        msg = bot.send_message(
            chat_id, "PIN слишком короткий. Введите минимум 4 символа:"
        )
        bot.register_next_step_handler(msg, process_setpin)
        return

    key = set_user_pin(chat_id, pin)
    UNLOCKED_KEYS[chat_id] = key
    user_pin_flow.pop(chat_id, None)

    bot.send_message(
        chat_id,
        "✅ PIN установлен.\n\n"
        "Ваши текущие и будущие задачи будут храниться зашифрованно.\n"
        "После перезапуска бота используйте /unlock.",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(commands=["unlock"])
def unlock_start(message):
    chat_id = message.chat.id

    if not user_has_pin(chat_id):
        bot.send_message(
            chat_id,
            "У вас ещё не настроен PIN. Используйте /setpin.",
            reply_markup=make_main_keyboard(),
        )
        return

    msg = bot.send_message(
        chat_id,
        "🔓 Введите PIN для доступа к зашифрованным задачам.\n\n"
        "Чтобы отменить, напишите: отмена",
    )

    user_pin_flow[chat_id] = "unlock"
    bot.register_next_step_handler(msg, process_unlock)


def process_unlock(message):
    chat_id = message.chat.id

    if is_cancel_text(message):
        user_pin_flow.pop(chat_id, None)
        bot.send_message(chat_id, "Отменено.", reply_markup=make_main_keyboard())
        return

    pin = message.text.strip() if message.text else ""
    key = unlock_user(chat_id, pin)

    if not key:
        msg = bot.send_message(chat_id, "❌ Неверный PIN. Попробуйте ещё раз:")
        bot.register_next_step_handler(msg, process_unlock)
        return

    UNLOCKED_KEYS[chat_id] = key
    encrypt_existing_user_tasks(chat_id, key)
    user_pin_flow.pop(chat_id, None)

    bot.send_message(
        chat_id,
        "✅ Доступ открыт. Зашифрованные задачи доступны.",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(commands=["lock"])
def lock_handler(message):
    chat_id = message.chat.id
    UNLOCKED_KEYS.pop(chat_id, None)

    bot.send_message(
        chat_id,
        "🔒 Доступ закрыт. Для просмотра задач используйте /unlock.",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(commands=["cancel"])
def cancel_handler(message):
    chat_id = message.chat.id
    user_creation_data.pop(chat_id, None)
    user_pin_flow.pop(chat_id, None)

    bot.send_message(
        chat_id,
        "Текущий сценарий отменён.",
        reply_markup=make_main_keyboard(),
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
    tasks = get_tasks_for_day(chat_id, day, get_user_key(chat_id))

    if not tasks:
        bot.send_message(
            chat_id,
            f"{title}\n\n🎉 Задач нет.",
            reply_markup=make_main_keyboard(),
        )
        return

    text = f"{title}\n\n"

    for _, task_title, remind_date in tasks:
        time_part = remind_date.split(" ")[1] if remind_date else "без времени"
        text += f"• {time_part} — {task_title}\n"

    bot.send_message(chat_id, text, reply_markup=make_main_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "today")
def today_callback(call):
    send_day_tasks(call.message.chat.id, get_now_msk(), "📅 Задачи на сегодня")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "tomorrow")
def tomorrow_callback(call):
    send_day_tasks(
        call.message.chat.id,
        get_now_msk() + timedelta(days=1),
        "🌅 Задачи на завтра",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "create_fast")
def start_fast_task(call):
    chat_id = call.message.chat.id

    msg = bot.send_message(
        chat_id,
        "⚡ Введите название быстрой задачи.\n\nЧтобы отменить, напишите: отмена",
    )

    bot.register_next_step_handler(msg, process_fast_task_title)
    bot.answer_callback_query(call.id)


def process_fast_task_title(message):
    chat_id = message.chat.id

    if is_cancel_text(message):
        bot.send_message(
            chat_id, "Создание задачи отменено.", reply_markup=make_main_keyboard()
        )
        return

    title_text = message.text if message.text else "Без названия"

    add_smart_task(
        user_id=chat_id,
        title=title_text,
        description=None,
        remind_date=None,
        encryption_key=get_user_key(chat_id),
    )

    bot.send_message(
        chat_id,
        format_task_created(title_text, None, None),
        reply_markup=make_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "create_smart")
def start_smart_task(call):
    chat_id = call.message.chat.id
    user_creation_data[chat_id] = {}

    msg = bot.send_message(
        chat_id,
        "📝 [Шаг 1/3] Введите заголовок задачи.\n\nЧтобы отменить, напишите: отмена",
    )

    bot.register_next_step_handler(msg, process_smart_title)
    bot.answer_callback_query(call.id)


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
        chat_id,
        "📄 [Шаг 2/3] Введите описание или напишите: пропустить",
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

    if desc_text.lower() == "пропустить":
        user_creation_data[chat_id]["description"] = None
    else:
        user_creation_data[chat_id]["description"] = desc_text

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
    remind_date = None if date_text.lower() == "пропустить" else date_text
    remind_date = normalize_remind_date(remind_date)

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
        user_id=chat_id,
        title=title,
        description=description,
        remind_date=remind_date,
        encryption_key=get_user_key(chat_id),
    )

    bot.send_message(
        chat_id,
        format_task_created(title, description, remind_date),
        reply_markup=make_main_keyboard(),
    )

    user_creation_data.pop(chat_id, None)


@bot.callback_query_handler(func=lambda call: call.data == "none")
def handle_none_button(call):
    bot.answer_callback_query(call.id)


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
        text="🧠 Maritaro AI Planner\nВыберите действие:",
        reply_markup=make_main_keyboard(),
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("view_"))
def view_task_details_handler(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    task = get_task_details(chat_id, task_id, get_user_key(chat_id))

    if not task:
        bot.answer_callback_query(call.id, "Задача не найдена или доступ ограничен!")
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
            "✅ Отметить выполненной",
            callback_data=f"complete_{task_id}",
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "⏰ Напомнить через 15 минут",
            callback_data=f"snooze15_{task_id}",
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "❌ Полностью удалить",
            callback_data=f"delete_{task_id}",
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад к списку задач",
            callback_data="go_to_list",
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
        text="🎉 Отлично! Задача выполнена.",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Выполнено!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("snooze15_"))
def handle_snooze_15(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    new_time = snooze_task(chat_id, task_id, 15)

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text=f"⏰ Хорошо, напомню ещё раз в {new_time} МСК.",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Напоминание перенесено")


@bot.callback_query_handler(func=lambda call: call.data.startswith("snooze60_"))
def handle_snooze_60(call):
    chat_id = call.message.chat.id
    task_id = int(call.data.split("_")[1])

    new_time = snooze_task(chat_id, task_id, 60)

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.id,
        text=f"⏰ Хорошо, напомню ещё раз в {new_time} МСК.",
        reply_markup=make_tasks_keyboard(chat_id),
    )

    bot.answer_callback_query(call.id, "Напоминание перенесено")


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

    markup.row(
        types.InlineKeyboardButton(
            "💥 ДА, УДАЛИТЬ ВСЁ",
            callback_data="execute_delete_all",
        ),
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="go_to_list",
        ),
    )

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


@bot.message_handler(content_types=["voice"])
def voice_handler(message):
    bot.send_message(
        message.chat.id,
        "🎤 Голосовые команды скоро появятся.\n\n"
        "Архитектура уже готова: voice → распознавание → ИИ → задача.",
        reply_markup=make_main_keyboard(),
    )


@bot.message_handler(func=lambda message: True, content_types=["text"])
def ai_message_handler(message):
    chat_id = message.chat.id
    text = message.text or ""

    if is_cancel_text(message):
        user_creation_data.pop(chat_id, None)
        user_pin_flow.pop(chat_id, None)
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

    status_msg = bot.send_message(
        chat_id,
        "🤖 Секунду, ИИ разбирает задачу...",
    )

    ai_result = parse_task_with_ai(text)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if "error" in ai_result:
        print(f"AI ERROR: {ai_result['error']}")

        bot.send_message(
            chat_id,
            "⚠️ ИИ временно недоступен.\n\n"
            "Задача не была создана автоматически. "
            "Используйте кнопку «Быстрая задача» или попробуйте позже.",
            reply_markup=make_main_keyboard(),
        )
        return

    title = ai_result.get("title")
    description = ai_result.get("description")
    remind_date = ai_result.get("remind_date")

    if not title:
        bot.send_message(
            chat_id,
            "❌ Я не понял задачу.\n\n"
            "Попробуйте так:\n"
            "«Напомни завтра в 14:00 купить молоко»",
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
        encryption_key=get_user_key(chat_id),
    )

    bot.send_message(
        chat_id,
        format_task_created(title, description, remind_date),
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

    print("Maritaro AI Planner запущен.")

    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
