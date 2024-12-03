import os
import json
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, EndpointConnectionError
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")

# Инициализация клиента для S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT_URL
)

# Путь к файлу данных на S3
S3_JSON_DB_PATH = "bot_data/users.json"
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

def load_data():
    """Загружает данные из JSON-файла с S3."""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=S3_JSON_DB_PATH)
        data = json.loads(response['Body'].read().decode())
        return data
    except s3_client.exceptions.NoSuchKey:
        logging.warning(f"Файл {S3_JSON_DB_PATH} не найден в S3, создаю новый.")
        return {"users": {}, "schedule": {}, "standard_schedule": {}}
    except (NoCredentialsError, PartialCredentialsError, EndpointConnectionError) as e:
        logging.error(f"Ошибка подключения к S3: {e}")
        raise
    except Exception as e:
        logging.error(f"Неизвестная ошибка при загрузке данных из S3: {e}")
        raise

def save_data(data):
    """Сохраняет данные в JSON-файл на S3."""
    try:
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=S3_JSON_DB_PATH, Body=json.dumps(data, indent=4))
        logging.info(f"Данные успешно сохранены в S3: {S3_JSON_DB_PATH}")
    except (NoCredentialsError, PartialCredentialsError, EndpointConnectionError) as e:
        logging.error(f"Ошибка подключения к S3: {e}")
    except Exception as e:
        logging.error(f"Неизвестная ошибка при сохранении данных в S3: {e}")

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
            ["Ученики", "Добавить расписание"],
            ["Просмотр расписания", "Редактировать расписание"],
            ["Сбросить расписание"]
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

async def students(update: Update, context: CallbackContext):
    """Отображает список всех учеников."""
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for info in data["users"].values():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)

async def add_schedule(update: Update, context: CallbackContext):
    """Добавляет расписание для нескольких учеников и выводит сообщение об успехе."""
    if not context.args:
        await update.message.reply_text(
            "Использование: /schedule\n"
            "@username день предмет время1 время2 ...\n\n"
            "Пример:\n"
            "/schedule @ivan123 Понедельник Математика 10:00 14:00"
        )
        return

    lines = " ".join(context.args).split("\n")
    data = load_data()  # Загружаем данные с S3
    messages = []

    if "schedule" not in data:
        logging.warning("Ключ 'schedule' отсутствует, создаю...")
        data["schedule"] = {}

    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 4:
            messages.append(f"Ошибка: недостаточно данных в строке: {line}")
            logging.warning(f"Недостаточно данных в строке: {line}")
            continue

        username, day, subject, *times = parts

        if day not in valid_days:
            messages.append(f"Ошибка: некорректный день недели: {day}")
            logging.warning(f"Некорректный день недели: {day}")
            continue

        user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)
        if not user_id:
            messages.append(f"Ошибка: пользователь {username} не найден.")
            logging.warning(f"Пользователь {username} не найден.")
            continue

        # Добавление расписания
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
                messages.append(f"Ошибка: некорректный формат времени {time} для {username}")
                logging.warning(f"Некорректный формат времени {time} для {username}")
                continue

        messages.append(f"Добавлено: {username} - {day} - {subject} в {', '.join(times)}")

    # Сохраняем данные в S3
    save_data(data)

    # Отправляем сообщение, что расписание добавлено
    await update.message.reply_text("\n".join(messages))

async def view_all_schedules(update: Update, context: CallbackContext):
    """Отображает расписание всех учеников."""
    data = load_data()
    if not data["schedule"]:
        await update.message.reply_text("Расписание пусто.")
        return

    schedule_text = "Расписание всех учеников:\n"
    for user_id, schedule in data["schedule"].items():
        user_info = data["users"].get(user_id, {})
        username = user_info.get("username", "Неизвестный пользователь")
        schedule_text += f"{username}:\n"
        for entry in schedule:
            schedule_text += f"  {entry['day']} {entry['time']} - {entry['description']}\n"
    await update.message.reply_text(schedule_text)

# --- Напоминания ---
async def send_reminder(update: Update, context: CallbackContext):
    """Отправляет напоминание о занятии через 1 час до начала."""
    data = load_data()
    now = datetime.now()

    for user_id, schedule in data["schedule"].items():
        for lesson in schedule:
            lesson_time = datetime.strptime(f"{lesson['day']} {lesson['time']}", "%A %H:%M")
            if now <= lesson_time <= (lesson_time + timedelta(hours=1)):
                if not lesson["reminder_sent_1h"]:
                    user_info = data["users"].get(str(user_id))
                    if user_info:
                        user_username = user_info["username"]
                        reminder_text = f"Напоминаем вам о занятии по {lesson['description']} через 1 час!"
                        await context.bot.send_message(user_username, reminder_text)
                        lesson["reminder_sent_1h"] = True
                        save_data(data)

# --- Планировщик ---
def setup_scheduler(application: Application):
    """Настройка планировщика для напоминаний о занятиях."""
    scheduler.add_job(send_reminder, IntervalTrigger(minutes=10), args=[None, application])
    scheduler.start()

# --- Основная функция и запуск ---
async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    setup_scheduler(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("add_schedule", add_schedule))
    application.add_handler(CommandHandler("view_schedule", view_all_schedules))

    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
