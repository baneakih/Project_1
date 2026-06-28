from telebot import types


def make_main_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)

    markup.add(
        types.InlineKeyboardButton("🗂 Показать все задачи", callback_data="go_to_list")
    )

    markup.row(
        types.InlineKeyboardButton("⚡ Быстрая задача", callback_data="create_fast"),
        types.InlineKeyboardButton("⏰ Умная задача", callback_data="create_smart"),
    )

    markup.row(
        types.InlineKeyboardButton("📅 Сегодня", callback_data="today"),
        types.InlineKeyboardButton("🌅 Завтра", callback_data="tomorrow"),
    )

    return markup


def make_reminder_keyboard(task_id: int):
    markup = types.InlineKeyboardMarkup()

    markup.row(
        types.InlineKeyboardButton("✅ Выполнено", callback_data=f"complete_{task_id}"),
        types.InlineKeyboardButton("⏰ +15 мин", callback_data=f"snooze15_{task_id}"),
    )

    markup.add(
        types.InlineKeyboardButton("⏰ +1 час", callback_data=f"snooze60_{task_id}")
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

    return text


def make_tasks_keyboard(tasks):
    markup = types.InlineKeyboardMarkup()

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
