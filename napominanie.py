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
S3_ACCESS_KEY = "0CLS24Z09YQL8UJLQCQQ"
S3_SECRET_KEY = '9GcBHRJY97YmWCHe0gXPrJnKgsFC8vqiyoT5GZPL'
S3_BUCKET_NAME = '8df8e63e-raspisanie'
S3_ENDPOINT_URL = 'https://s3.timeweb.cloud'


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

async def add_schedule(update: Update, context: CallbackContext):
    """Добавляет расписание."""
    if not context.args:
        await update.message.reply_text(
            "Использование: /schedule @username Понедельник Предмет 10:00 12:00"
        )
        return

    data = load_data()
    args = context.args
    username, day, subject, *times = args

    user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)
    if not user_id:
        await update.message.reply_text(f"Пользователь {username} не найден.")
        return

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
            await update.message.reply_text(f"Некорректное время: {time}")
            return

    save_data(data)
    await update.message.reply_text(f"Расписание добавлено для {username}.")

async def view_schedule(update: Update, context: CallbackContext):
    """Отображает расписание всех учеников."""
    data = load_data()
    if not data["schedule"]:
        await update.message.reply_text("Расписание пусто.")
        return

    schedule_text = "Расписание:\n"
    for user_id, schedule in data["schedule"].items():
        user_info = data["users"].get(user_id, {})
        username = user_info.get("username", "Неизвестный пользователь")
        schedule_text += f"{username}:\n"
        for lesson in schedule:
            schedule_text += f"  {lesson['day']} {lesson['time']} - {lesson['description']}\n"
    await update.message.reply_text(schedule_text)

async def reset_schedule(update: Update, context: CallbackContext):
    """Сбрасывает расписание."""
    data = load_data()
    data["schedule"] = {}
    save_data(data)
    await update.message.reply_text("Расписание сброшено.")

# --- Напоминания ---
async def send_reminder(application: Application):
    """Отправляет напоминания."""
    data = load_data()
    now = datetime.now()

    for user_id, schedule in data.get("schedule", {}).items():
        for lesson in schedule:
            lesson_time = datetime.strptime(f"{lesson['day']} {lesson['time']}", "%A %H:%M")
            if lesson_time - timedelta(hours=1) <= now <= lesson_time and not lesson["reminder_sent_1h"]:
                await application.bot.send_message(chat_id=user_id, text=f"Напоминание: скоро урок {lesson['description']}.")
                lesson["reminder_sent_1h"] = True
                save_data(data)

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
    application.add_handler(CommandHandler("schedule", add_schedule))
    application.add_handler(CommandHandler("view_schedule", view_schedule))
    application.add_handler(CommandHandler("reset_schedule", reset_schedule))

    # Запуск бота
    await application.run_polling()

# --- Запуск ---
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Остановка бота.")
