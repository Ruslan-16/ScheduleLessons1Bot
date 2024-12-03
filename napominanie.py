import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
import locale
import boto3
from botocore.exceptions import NoCredentialsError, EndpointConnectionError

# --- Инициализация окружения ---
load_dotenv()

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")

# Настройка клиента S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT_URL
)

# Пути и файлы
S3_JSON_DB_PATH = "bot_data/users.json"
LOG_DIR = "/persistent_data"
LOG_FILE_PATH = f"{LOG_DIR}/logs.txt"

# Создание директории для логов
os.makedirs(LOG_DIR, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    filename=LOG_FILE_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Устанавливаем локаль
try:
    locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
except locale.Error:
    logger.warning("Локализация 'ru_RU.UTF-8' не поддерживается. Используйте английские дни недели.")

# --- Вспомогательные функции ---
def load_data():
    """Загружает данные из S3."""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=S3_JSON_DB_PATH)
        return json.loads(response['Body'].read().decode())
    except s3_client.exceptions.NoSuchKey:
        logger.info(f"Файл {S3_JSON_DB_PATH} не найден, создаётся новый.")
        return {"users": {}, "schedule": {}, "standard_schedule": {}}
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных из S3: {e}")
        raise

def save_data(data):
    """Сохраняет данные в S3."""
    try:
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=S3_JSON_DB_PATH, Body=json.dumps(data, indent=4))
        logger.info(f"Данные успешно сохранены в S3: {S3_JSON_DB_PATH}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в S3: {e}")

# --- Команды бота ---
async def start(update: Update, context: CallbackContext):
    """Регистрация пользователя."""
    user = update.effective_user
    data = load_data()

    # Добавляем пользователя
    data["users"][str(user.id)] = {"username": user.username, "first_name": user.first_name}
    save_data(data)

    if str(user.id) == ADMIN_ID:
        admin_keyboard = [
            ["Ученики", "Добавить расписание"],
            ["Просмотр расписания", "Сбросить расписание"]
        ]
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Выберите команду:",
            reply_markup=ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        )
    else:
        await update.message.reply_text("Вы зарегистрированы!")

async def students(update: Update, context: CallbackContext):
    """Список всех учеников."""
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for user_id, info in data["users"].items():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)

async def send_reminder(application: Application):
    """Отправляет напоминания."""
    data = load_data()
    now = datetime.now()

    for user_id, schedule in data.get("schedule", {}).items():
        for lesson in schedule:
            try:
                lesson_time = datetime.strptime(f"{lesson['day']} {lesson['time']}", "%A %H:%M")
                if lesson_time - timedelta(hours=1) <= now <= lesson_time and not lesson["reminder_sent_1h"]:
                    await application.bot.send_message(chat_id=user_id, text=f"Напоминание: скоро урок {lesson['description']}.")
                    lesson["reminder_sent_1h"] = True
                    save_data(data)
            except Exception as e:
                logger.error(f"Ошибка при обработке напоминания для пользователя {user_id}: {e}")

# --- Планировщик ---
def setup_scheduler(application: Application):
    """Настройка планировщика."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminder, IntervalTrigger(minutes=10), args=[application])
    scheduler.start()

# --- Основная функция ---
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Настройка планировщика
    setup_scheduler(application)

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))

    # Запуск бота
    await application.run_polling()

# --- Запуск ---
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            logger.info("Остановка бота.")
