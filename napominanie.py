import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Конфигурация логирования ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Константы ---
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # Укажите ваш токен
ADMIN_ID = 123456789  # Укажите ID администратора
TIME_OFFSET = timedelta(hours=3)

# --- Глобальные данные (хранятся в памяти) ---
data = {
    "users": {},  # Список пользователей
    "schedule": {},  # Расписания
    "standard_schedule": {}  # Стандартное расписание
}

scheduler = AsyncIOScheduler()


# --- Вспомогательные функции ---
def parse_lesson_datetime(day: str, time: str):
    """Парсит день недели и время в объект datetime."""
    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    if day not in valid_days:
        return None

    day_index = valid_days.index(day)
    now = datetime.now()
    target_date = now + timedelta(days=(day_index - now.weekday()) % 7)
    try:
        lesson_time = datetime.strptime(time, "%H:%M").time()
        return datetime.combine(target_date, lesson_time)
    except ValueError:
        return None


# --- Напоминания ---
async def send_reminders(application: Application):
    """Отправляет напоминания за 1 и за 24 часа до занятия."""
    logging.info("Функция send_reminders запущена.")
    now = datetime.now() + TIME_OFFSET

    for user_id, schedule in data.get("schedule", {}).items():
        for entry in schedule:
            lesson_time = parse_lesson_datetime(entry["day"], entry["time"])
            if not lesson_time:
                logging.warning(f"Некорректное время или день: {entry}")
                continue

            time_diff = lesson_time - now

            # Напоминание за 24 часа
            if 23 <= time_diff.total_seconds() / 3600 <= 24 and not entry.get("reminder_sent_24h"):
                logging.info(f"Отправляем напоминание за 24 часа для пользователя {user_id}.")
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: Завтра в {entry['time']} у вас {entry['description']}."
                )
                entry["reminder_sent_24h"] = True

            # Напоминание за 1 час
            elif 0 < time_diff.total_seconds() / 3600 <= 1 and not entry.get("reminder_sent_1h"):
                logging.info(f"Отправляем напоминание за 1 час для пользователя {user_id}.")
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: Через 1 час в {entry['time']} у вас {entry['description']}."
                )
                entry["reminder_sent_1h"] = True


# --- Команды ---
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user = update.effective_user

    # Добавляем пользователя в память
    data["users"][str(user.id)] = {"username": user.username, "first_name": user.first_name}
    logging.info(f"Пользователь {user.username} ({user.id}) зарегистрирован.")

    if user.id == ADMIN_ID:
        admin_keyboard = [
            ["Добавить расписание"],
            ["Ученики", "Просмотр расписания всех"],
            ["Редактировать расписание", "Сбросить к стандартному"]
        ]
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Выберите команду:",
            reply_markup=ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        )
    else:
        user_keyboard = [["Мое расписание"]]
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=ReplyKeyboardMarkup(user_keyboard, resize_keyboard=True)
        )


async def students(update: Update, _):
    """Отображает список всех учеников."""
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for info in data["users"].values():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)


async def view_all_schedules(update: Update, _):
    """Отображает расписание всех учеников."""
    if not data["schedule"]:
        await update.message.reply_text("Расписание пусто.")
        return

    schedule_text = "Расписание всех учеников:\n"
    for user_id, schedule in data["schedule"].items():
        user_info = data["users"].get(user_id, {})
        username = user_info.get("username", "Неизвестно")
        first_name = user_info.get("first_name", "Неизвестно")
        schedule_text += f"{first_name} (@{username}):\n"
        for entry in schedule:
            schedule_text += f"  {entry['day']} {entry['time']} - {entry['description']}\n"
    await update.message.reply_text(schedule_text)


async def add_schedule(update: Update, context: CallbackContext):
    """Добавляет расписание для нескольких учеников."""
    if not context.args:
        await update.message.reply_text(
            "Использование: /schedule\n"
            "@username день предмет время1 время2 ...\n\n"
            "Пример:\n"
            "/schedule @ivan123 Понедельник Математика 10:00 14:00"
        )
        return

    lines = " ".join(context.args).split("\n")
    messages = []

    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 4:
            messages.append(f"Ошибка: недостаточно данных в строке: {line}")
            continue

        username, day, subject, *times = parts
        if day not in valid_days:
            messages.append(f"Ошибка: некорректный день недели: {day}")
            continue

        user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)
        if not user_id:
            messages.append(f"Ошибка: пользователь {username} не найден.")
            continue

        data["schedule"].setdefault(user_id, [])
        for time in times:
            try:
                datetime.strptime(time, "%H:%M")
                data["schedule"][user_id].append({
                    "day": day,
                    "time": time,
                    "description": subject,
                    "reminder_sent_1h": False,
                    "reminder_sent_24h": False
                })
            except ValueError:
                messages.append(f"Ошибка: некорректный формат времени {time}")
                continue

        messages.append(f"Добавлено: {username} - {day} - {subject} в {', '.join(times)}")

    await update.message.reply_text("\n".join(messages))


async def my_schedule(update: Update, _):
    """Отображает расписание ученика."""
    user_id = str(update.effective_user.id)
    schedule = data.get("schedule", {}).get(user_id, [])
    if not schedule:
        await update.message.reply_text("Ваше расписание пусто.")
        return

    schedule_text = "Ваше расписание:\n"
    for entry in schedule:
        schedule_text += f"{entry['day']} {entry['time']} - {entry['description']}\n"
    await update.message.reply_text(schedule_text)


# --- Основная функция ---
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Планировщик задач
    scheduler.add_job(send_reminders, CronTrigger(minute="*/10"), args=[application])
    scheduler.start()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("view_all_schedules", view_all_schedules))
    application.add_handler(CommandHandler("schedule", add_schedule))
    application.add_handler(CommandHandler("my_schedule", my_schedule))

    logging.info("Бот запущен.")
    application.run_polling()


if __name__ == "__main__":
    main()
