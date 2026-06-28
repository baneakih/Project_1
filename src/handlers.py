from datetime import timedelta

from database import get_tasks_for_day, get_user_stats
from keyboards import make_main_keyboard
from utils import get_now_msk


def register_command_handlers(bot, user_creation_data: dict[int, dict]):
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
            chat_id,
            "Текущий сценарий отменён.",
            reply_markup=make_main_keyboard(),
        )

    @bot.message_handler(commands=["today"])
    def today_handler(message):
        send_day_tasks(
            bot,
            message.chat.id,
            get_now_msk(),
            "📅 Задачи на сегодня",
        )

    @bot.message_handler(commands=["tomorrow"])
    def tomorrow_handler(message):
        send_day_tasks(
            bot,
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


def send_day_tasks(bot, chat_id: int, day, title: str):
    tasks = get_tasks_for_day(chat_id, day)

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

    bot.send_message(
        chat_id,
        text,
        reply_markup=make_main_keyboard(),
    )
