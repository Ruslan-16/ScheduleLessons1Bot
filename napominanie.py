import os
import json
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiobotocore.session import get_session

# --- Константы и настройки ---
LOG_DIR = "/persistent_data"
LOG_FILE_PATH = f"{LOG_DIR}/logs.txt"
JSON_DB_PATH = "/persistent_data/users.json"

# Настройки S3
S3_BUCKET = os.getenv("S3_BUCKET_NAME", "8df8e63e-raspisanie")
S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "https://s3.timeweb.cloud")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")

# Переменные окружения для бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Временная зона
TIME_OFFSET = timedelta(hours=3)

# Проверка переменных окружения
if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
if ADMIN_ID == 0:
    raise ValueError("Переменная окружения ADMIN_ID не установлена или равна 0!")

# --- Настройка логирования ---
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# --- Асинхронный S3 клиент ---
async def get_s3_client():
    """Создаёт асинхронный клиент S3."""
    session = get_session()
    return session.create_client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )

# --- Вспомогательные функции ---
async def upload_to_s3():
    """Загружает JSON-базу данных в S3."""
    try:
        if not os.path.exists(JSON_DB_PATH):
            logging.warning(f"Файл {JSON_DB_PATH} не найден для загрузки в S3.")
            return

        async with await get_s3_client() as client:
            logging.info(f"Загружаю файл {JSON_DB_PATH} в бакет {S3_BUCKET}...")
            await client.upload_file(JSON_DB_PATH, S3_BUCKET, "users.json")
            logging.info("Файл базы данных успешно загружен в S3.")
    except Exception as e:
        logging.error(f"Ошибка при загрузке в S3: {e}")


async def download_from_s3():
    """Скачивает JSON-базу данных из S3."""
    try:
        async with await get_s3_client() as client:
            await client.download_file(S3_BUCKET, "users.json", JSON_DB_PATH)
            logging.info("Файл базы данных успешно скачан из S3.")
    except Exception as e:
        logging.warning(f"Не удалось скачать файл из S3: {e}")


async def init_json_db():
    """Создаёт файл базы данных, если его нет."""
    os.makedirs(os.path.dirname(JSON_DB_PATH), exist_ok=True)
    if not os.path.exists(JSON_DB_PATH):
        logging.info(f"Создаю файл базы данных {JSON_DB_PATH}...")
        with open(JSON_DB_PATH, "w") as f:
            json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)
        await upload_to_s3()  # Используйте await для асинхронной функции


def load_data():
    """Загружает данные из JSON-файла."""
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()
    with open(JSON_DB_PATH, "r") as f:
        return json.load(f)


def save_data(data):
    """Сохраняет данные в JSON с временным файлом."""
    with tempfile.NamedTemporaryFile(delete=False, dir=os.path.dirname(JSON_DB_PATH)) as tmp_file:
        json.dump(data, tmp_file, indent=4)
        tmp_path = tmp_file.name
    shutil.move(tmp_path, JSON_DB_PATH)
    logging.info(f"Данные успешно сохранены в {JSON_DB_PATH}")


async def reset_to_standard_schedule():
    """Сбрасывает расписание на стандартное."""
    data = load_data()
    if "standard_schedule" in data:
        data["schedule"] = data["standard_schedule"]
        save_data(data)
        await upload_to_s3()


# --- Telegram-команды ---
async def start(update: Update, context: CallbackContext):
    """Команда /start."""
    user = update.effective_user
    data = load_data()

    # Регистрируем пользователя
    data["users"][str(user.id)] = {"username": user.username, "first_name": user.first_name}
    save_data(data)

    if user.id == ADMIN_ID:
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Добавить расписание", callback_data="add_schedule")],
            [InlineKeyboardButton("Ученики", callback_data="view_students")],
            [InlineKeyboardButton("Просмотр расписания всех", callback_data="view_schedules")],
            [InlineKeyboardButton("Сбросить к стандартному", callback_data="reset_schedule")],
        ])
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Выберите команду:",
            reply_markup=admin_keyboard,
        )
    else:
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях."
        )


async def handle_admin_button_callback(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопок администратора."""
    query = update.callback_query
    await query.answer()

    if query.data == "add_schedule":
        await query.message.reply_text(
            "Пример:\n"
            "`/schedule @ivan123 Понедельник Английский 10:00 14:00`",
            parse_mode="Markdown",
        )
    elif query.data == "view_students":
        await students(update, context)
    elif query.data == "view_schedules":
        await view_all_schedules(update, context)
    elif query.data == "reset_schedule":
        await reset_to_standard_schedule()
        await query.message.reply_text("Расписание сброшено к стандартному.")
    else:
        await query.message.reply_text("Неизвестная команда.")


async def students(update: Update, _):
    """Команда /students."""
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for info in data["users"].values():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)


async def view_all_schedules(update: Update, _):
    """Команда просмотра всех расписаний."""
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


async def send_reminders(context: CallbackContext):
    """Отправляет напоминания о занятиях."""
    data = load_data()
    now = datetime.now() + TIME_OFFSET

    for user_id, schedule in data["schedule"].items():
        for entry in schedule:
            entry_time = datetime.strptime(entry["time"], "%H:%M")
            reminder_time = datetime.combine(now.date(), entry_time.time()) - timedelta(hours=1)

            if now >= reminder_time and not entry.get("reminder_sent_1h", False):
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"Напоминание: {entry['description']} начнётся через час.",
                    )
                    entry["reminder_sent_1h"] = True
                except Exception as e:
                    logging.error(f"Не удалось отправить уведомление для пользователя {user_id}: {e}")

    save_data(data)


# --- Основная функция ---
async def main():
    """Запуск бота."""
    await init_json_db()

    application = Application.builder().token(BOT_TOKEN).build()

    # Планировщик задач
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reset_to_standard_schedule,
        CronTrigger(day_of_week="sat", hour=23, minute=59),
    )
    scheduler.add_job(send_reminders, "interval", minutes=1, args=[application])
    scheduler.start()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_admin_button_callback))

    # Запуск бота
    await application.run_polling()
    logging.info("Бот запущен.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

