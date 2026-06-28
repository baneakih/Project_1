from datetime import timedelta

from telebot import types

from database import (
    add_smart_task,
    delete_all_tasks_permanently,
    delete_task_permanently,
    get_all_active_tasks,
    get_task_details,
    snooze_task,
    toggle_user_task_status,
)

from handlers import send_day_tasks
from keyboards import (
    format_task_created,
    make_main_keyboard,
    make_tasks_keyboard,
)
from utils import get_now_msk, normalize_remind_date


def answer_callback(bot, call, text: str | None = None) -> None:
    try:
        bot.answer_callback_query(call.id, text=text)
    except Exception as e:
        error_text = str(e).lower()
        ignored_errors = [
            "query is too old",
            "response timeout expired",
            "query id is invalid",
        ]

        if not any(error in error_text for error in ignored_errors):
            print(f"Ошибка answer_callback_query: {e}")


def safe_edit_message_text(
    bot, chat_id: int, message_id: int, text: str, reply_markup=None
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
    bot, chat_id: int, message_id: int, reply_markup=None
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


def get_tasks_keyboard(user_id: int):
    tasks = get_all_active_tasks(user_id)
    return make_tasks_keyboard(tasks)


def register_callback_handlers(bot, user_creation_data: dict[int, dict]):
    @bot.callback_query_handler(func=lambda call: call.data == "today")
    def today_callback(call):
        answer_callback(bot, call)
        send_day_tasks(
            bot,
            call.message.chat.id,
            get_now_msk(),
            "📅 Задачи на сегодня",
        )

    @bot.callback_query_handler(func=lambda call: call.data == "tomorrow")
    def tomorrow_callback(call):
        answer_callback(bot, call)
        send_day_tasks(
            bot,
            call.message.chat.id,
            get_now_msk() + timedelta(days=1),
            "🌅 Задачи на завтра",
        )

    @bot.callback_query_handler(func=lambda call: call.data == "create_fast")
    def start_fast_task(call):
        answer_callback(bot, call)
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
                chat_id,
                "Создание задачи отменено.",
                reply_markup=make_main_keyboard(),
            )
            return

        title_text = message.text if message.text else "Без названия"
        add_smart_task(
            user_id=chat_id,
            title=title_text,
            description=None,
            remind_date=None,
        )
        bot.send_message(
            chat_id,
            format_task_created(title_text, None, None),
            reply_markup=make_main_keyboard(),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "create_smart")
    def start_smart_task(call):
        answer_callback(bot, call)
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
                chat_id,
                "Создание задачи отменено.",
                reply_markup=make_main_keyboard(),
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
                chat_id,
                "Создание задачи отменено.",
                reply_markup=make_main_keyboard(),
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
                chat_id,
                "Создание задачи отменено.",
                reply_markup=make_main_keyboard(),
            )
            return

        date_text = message.text if message.text else ""

        remind_date = (
            None
            if date_text.lower() == "пропустить"
            else normalize_remind_date(date_text)
        )

        if date_text.lower() != "пропустить" and not remind_date:
            msg = bot.send_message(
                chat_id,
                "❌ Неверный формат даты.\n\n"
                "Дата должна быть в будущем и в формате:\n"
                "22.06.2026 18:30\n\n"
                "Или напишите: пропустить",
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
        )

        bot.send_message(
            chat_id,
            format_task_created(title, description, remind_date),
            reply_markup=make_main_keyboard(),
        )

        user_creation_data.pop(chat_id, None)

    @bot.callback_query_handler(func=lambda call: call.data == "none")
    def handle_none_button(call):
        answer_callback(bot, call)

    @bot.callback_query_handler(func=lambda call: call.data == "go_to_list")
    def handle_to_list(call):
        answer_callback(bot, call)

        chat_id = call.message.chat.id

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text="🗂 Ваш список активных задач:",
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "go_to_main")
    def handle_to_main(call):
        answer_callback(bot, call)

        safe_edit_message_text(
            bot=bot,
            chat_id=call.message.chat.id,
            message_id=call.message.id,
            text="🧠 Maritaro AI Planner\nВыберите действие:",
            reply_markup=make_main_keyboard(),
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("view_"))
    def view_task_details_handler(call):
        answer_callback(bot, call)

        chat_id = call.message.chat.id
        task_id = int(call.data.split("_")[1])

        task = get_task_details(chat_id, task_id)

        if not task:
            answer_callback(bot, call, "Задача не найдена!")
            return

        _, title, description, remind_date, status, reminder_sent = task

        desc_text = description if description else "Описание отсутствует"
        date_text = remind_date if remind_date else "Не указано"
        remind_status = "Да" if reminder_sent else "Нет"

        info_msg = (
            f"📋 Задача: {title}\n\n"
            f"📄 Описание: {desc_text}\n"
            f"⏰ Напоминание: {date_text}\n"
            f"🔔 Уведомление отправлено: {remind_status}"
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
                "⏰ Напомнить через 1 час",
                callback_data=f"snooze60_{task_id}",
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

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text=info_msg,
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("complete_"))
    def handle_complete(call):
        answer_callback(bot, call, "Выполнено!")

        chat_id = call.message.chat.id
        task_id = int(call.data.split("_")[1])

        toggle_user_task_status(chat_id, task_id)

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text="🎉 Отлично! Задача выполнена.",
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("snooze15_"))
    def handle_snooze_15(call):
        answer_callback(bot, call, "Напоминание перенесено")

        chat_id = call.message.chat.id
        task_id = int(call.data.split("_")[1])

        new_time = snooze_task(chat_id, task_id, 15)

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text=f"⏰ Хорошо, напомню ещё раз в {new_time} МСК.",
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("snooze60_"))
    def handle_snooze_60(call):
        answer_callback(bot, call, "Напоминание перенесено")

        chat_id = call.message.chat.id
        task_id = int(call.data.split("_")[1])

        new_time = snooze_task(chat_id, task_id, 60)

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text=f"⏰ Хорошо, напомню ещё раз в {new_time} МСК.",
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
    def handle_delete(call):
        answer_callback(bot, call, "Удалено!")

        chat_id = call.message.chat.id
        task_id = int(call.data.split("_")[1])

        delete_task_permanently(chat_id, task_id)

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text="🗑 Задача полностью удалена.",
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("listdelete_"))
    def handle_list_delete(call):
        answer_callback(bot, call, "Задача удалена!")

        chat_id = call.message.chat.id
        task_id = int(call.data.split("_")[1])

        delete_task_permanently(chat_id, task_id)

        safe_edit_message_reply_markup(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "confirm_delete_all")
    def ask_for_delete_all(call):
        answer_callback(bot, call)

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

        safe_edit_message_text(
            bot=bot,
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
        answer_callback(bot, call, "Задачи удалены!")

        chat_id = call.message.chat.id

        delete_all_tasks_permanently(chat_id)

        safe_edit_message_text(
            bot=bot,
            chat_id=chat_id,
            message_id=call.message.id,
            text="🚨 Ваш личный список очищен. Все ваши задачи удалены.",
            reply_markup=get_tasks_keyboard(chat_id),
        )

    @bot.callback_query_handler(func=lambda call: True)
    def global_callback_catcher(call):
        answer_callback(bot, call)
