import os
import threading

import telebot
from dotenv import load_dotenv

from callbacks import register_callback_handlers
from database import init_db
from handlers import register_command_handlers
from message_handlers import register_message_handlers
from reminders import check_reminders

load_dotenv()
init_db()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=8)
user_creation_data: dict[int, dict] = {}

register_command_handlers(bot, user_creation_data)
register_callback_handlers(bot, user_creation_data)
register_message_handlers(bot, user_creation_data)


if __name__ == "__main__":
    reminder_thread = threading.Thread(
        target=check_reminders,
        args=(bot,),
        daemon=True,
    )
    reminder_thread.start()

    print("Maritaro AI Planner запущен.")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
