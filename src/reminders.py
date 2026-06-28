import time

from database import get_global_active_reminders, mark_reminder_sent
from keyboards import make_reminder_keyboard
from utils import get_now_msk


def check_reminders(bot):
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
