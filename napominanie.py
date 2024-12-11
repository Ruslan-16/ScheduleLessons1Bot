import os
import json
import logging
import shutil
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import boto3
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv(dotenv_path="документы.env")

# --- Константы и настройки ---
LOG_DIR = "/persistent_data"
LOG_FILE_PATH = f"{LOG_DIR}/logs.txt"
JSON_DB_PATH = "/persistent_data/users.json"

# Настройки S3
S3_BUCKET = os.getenv("S3_BUCKET", "8df8e63e-raspisanie")
S3_ENDPOINT = "https://s3.timeweb.cloud"
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY", "Ваш_Access_Key")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY", "Ваш_Secret_Key")


# Проверьте переменные

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
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- S3 клиент ---
s3 = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    config=Config(signature_version="s3v4")
)

# --- Вспомогательные функции ---
def init_json_db():
    """Создаёт файл базы данных, если его нет."""
    os.makedirs(os.path.dirname(JSON_DB_PATH), exist_ok=True)
    if not os.path.exists(JSON_DB_PATH):
        logging.info(f"Создаю файл базы данных {JSON_DB_PATH}...")
        with open(JSON_DB_PATH, 'w') as f:
            json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)
        upload_to_s3()
    else:
        logging.info(f"Файл базы данных {JSON_DB_PATH} уже существует.")

def upload_to_s3():
    """Загружает JSON-базу данных в S3."""
    if not os.path.exists(JSON_DB_PATH):
        logging.warning(f"Файл {JSON_DB_PATH} не найден для загрузки в S3.")
        return
    s3.upload_file(JSON_DB_PATH, S3_BUCKET, "users.json")
    logging.info("Файл базы данных загружен в S3.")

def download_from_s3():
    """Скачивает JSON-базу данных из S3."""
    try:
        s3.download_file(S3_BUCKET, "users.json", JSON_DB_PATH)
        logging.info("Файл базы данных успешно скачан из S3.")
    except Exception as e:
        logging.warning(f"Не удалось скачать файл из S3: {e}")

def load_data():
    """Загружает данные из JSON-файла."""
    download_from_s3()
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()
    with open(JSON_DB_PATH, 'r') as f:
        return json.load(f)

def save_data(data):
    """Сохраняет данные в JSON-файл и загружает их в S3."""
    backup_path = f"{JSON_DB_PATH}.backup"
    if os.path.exists(JSON_DB_PATH):
        shutil.copy(JSON_DB_PATH, backup_path)
        logging.info(f"Резервная копия создана: {backup_path}")

    with open(JSON_DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)
    logging.info(f"Данные успешно сохранены в {JSON_DB_PATH}")
    upload_to_s3()

# --- Telegram-команды ---
async def start(update: Update, context: CallbackContext):
    """Команда /start."""
    user = update.effective_user
    data = load_data()

    # Регистрируем пользователя
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
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях."
        )

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

async def reset_to_standard_schedule(update: Update, _):
    """Сбрасывает расписание к стандартному."""
    data = load_data()
    if "standard_schedule" in data:
        data["schedule"] = data["standard_schedule"]
        save_data(data)
        await update.message.reply_text("Расписание сброшено к стандартному.")
    else:
        await update.message.reply_text("Стандартное расписание отсутствует.")

# --- Основная функция ---
def main():
    """Запуск бота."""
    init_json_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Планировщик задач
    scheduler = AsyncIOScheduler()
    scheduler.start()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("view_all_schedules", view_all_schedules))
    application.add_handler(CommandHandler("reset", reset_to_standard_schedule))

    logging.info("Бот запущен.")
    application.run_polling()

if __name__ == "__main__":
    main()
