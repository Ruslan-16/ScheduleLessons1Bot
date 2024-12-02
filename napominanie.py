import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import shutil

LOG_DIR = "/persistent_data"
LOG_FILE_PATH = f"{LOG_DIR}/logs.txt"

# Убедимся, что директория существует
os.makedirs(LOG_DIR, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    filename=LOG_FILE_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
JSON_DB_PATH = os.getenv("JSON_DB_PATH", "/persistent_data/users.json")
scheduler = AsyncIOScheduler()

if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
if ADMIN_ID == 0:
    raise ValueError("Переменная окружения ADMIN_ID не установлена или равна 0!")

# --- Вспомогательные функции ---
def init_json_db():
    """Создаёт файл базы данных, если его нет."""
    os.makedirs(os.path.dirname(JSON_DB_PATH), exist_ok=True)
    if not os.path.exists(JSON_DB_PATH):
        logging.info(f"Создаю файл базы данных {JSON_DB_PATH}...")
        with open(JSON_DB_PATH, 'w') as f:
            json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)
    else:
        logging.info(f"Файл базы данных {JSON_DB_PATH} уже существует.")


def backup_json_file():
    """Создаёт резервную копию файла данных."""
    backup_path = f"{JSON_DB_PATH}.backup"
    if os.path.exists(JSON_DB_PATH):
        shutil.copy(JSON_DB_PATH, backup_path)
        logging.info(f"Резервная копия создана: {backup_path}")


def load_data():
    """Загружает данные из JSON-файла."""
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()
    with open(JSON_DB_PATH, 'r') as f:
        return json.load(f)


def save_data(data):
    """Сохраняет данные в JSON-файл с резервным копированием."""
    # Создаём резервную копию перед записью
    backup_path = f"{JSON_DB_PATH}.backup"
    if os.path.exists(JSON_DB_PATH):
        shutil.copy(JSON_DB_PATH, backup_path)
        logging.info(f"Резервная копия создана: {backup_path}")

    # Сохраняем данные
    with open(JSON_DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)
    logging.info(f"Данные успешно сохранены в {JSON_DB_PATH}")


TIME_OFFSET = timedelta(hours=3)

# --- Напоминания ---
async def send_reminders(application: Application):
    """Отправляет напоминания за 1 и за 24 часа до занятия."""
    logging.info("Функция send_reminders запущена.")  # Лог начала выполнения
    data = load_data()
    now = datetime.now() + TIME_OFFSET  # Корректируем текущее время
    logging.info(f"Текущее время (с учетом смещения): {now}")

    for user_id, schedule in data.get("schedule", {}).items():
        logging.info(f"Обрабатываем расписание для пользователя: {user_id}")
        for entry in schedule:
            lesson_time = parse_lesson_datetime(entry["day"], entry["time"])
            if not lesson_time:
                logging.warning(f"Некорректное время или день: {entry}")
                continue

            time_diff = lesson_time - now
            logging.info(
                f"Проверяем занятие: {entry['description']} в {entry['time']} ({entry['day']}). "
                f"До занятия: {time_diff.total_seconds() / 3600:.2f} часов."
            )

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

    save_data(data)
    logging.info("Завершено выполнение send_reminders. Данные сохранены.")


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


# --- Команды ---
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user = update.effective_user
    data = load_data()

    # Добавляем пользователя
    data["users"][str(user.id)] = {"username": user.username, "first_name": user.first_name}
    save_data(data)

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
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for info in data["users"].values():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)


async def view_all_schedules(update: Update, _):
    """Отображает расписание всех учеников."""
    data = load_data()
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
    data = load_data()
    messages = []

    # Проверка наличия ключа schedule
    if "schedule" not in data:
        logging.warning("Ключ 'schedule' отсутствует, создаю...")
        data["schedule"] = {}

    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    for line in lines:
        split_line = line.split()
        if len(split_line) < 3:
            messages.append(f"Ошибка: Неверный формат для записи: {line}")
            continue

        username, day, *times = split_line
        if day not in valid_days:
            messages.append(f"Ошибка: Некорректный день недели в записи: {line}")
            continue

        user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)
        if user_id is None:
            messages.append(f"Ошибка: пользователь {username} не найден.")
            logging.warning(f"Пользователь {username} не найден.")
            continue

        schedule = data["schedule"].get(user_id, [])
        for time in times:
            schedule.append({
                "day": day,
                "time": time,
                "description": "Неизвестно",
                "reminder_sent_24h": False,
                "reminder_sent_1h": False
            })
        data["schedule"][user_id] = schedule
        messages.append(f"Добавлено расписание для {username}: {day} {', '.join(times)}")

    save_data(data)

    # Вывод сообщений
    if messages:
        await update.message.reply_text("\n".join(messages))


async def reset_to_standard_schedule(update: Update, _):
    """Сброс расписания к стандартному."""
    data = load_data()
    standard_schedule = data.get("standard_schedule", {})

    if not standard_schedule:
        await update.message.reply_text("Стандартное расписание не найдено.")
        return

    data["schedule"] = standard_schedule
    save_data(data)
    await update.message.reply_text("Расписание сброшено к стандартному.")


def main():
    """Запуск бота."""
    init_json_db()

    # Создаём приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("view_all_schedules", view_all_schedules))
    application.add_handler(CommandHandler("schedule", add_schedule))
    application.add_handler(CommandHandler("reset_schedule", reset_to_standard_schedule))

    # Напоминания
    scheduler.add_job(send_reminders, CronTrigger(hour="0-23", minute="*/30", second="0", timezone="Europe/Moscow"))

    # Запуск
    application.run_polling()


if __name__ == '__main__':
    main()
