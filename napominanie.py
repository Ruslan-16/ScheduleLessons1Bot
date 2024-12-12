import os
import json
import logging
import shutil
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import boto3
from botocore.client import Config

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
    try:
        if not os.path.exists(JSON_DB_PATH):
            logging.warning(f"Файл {JSON_DB_PATH} не найден для загрузки в S3.")
            return

        logging.info(f"Загружаю файл {JSON_DB_PATH} в бакет {S3_BUCKET}...")
        s3.upload_file(JSON_DB_PATH, S3_BUCKET, "users.json")
        logging.info("Файл базы данных успешно загружен в S3.")
    except Exception as e:
        logging.error(f"Ошибка при загрузке в S3: {e}")

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

def reset_to_standard_schedule():
    """Сбрасывает расписание на стандартное."""
    data = load_data()
    if "standard_schedule" in data:
        data["schedule"] = data["standard_schedule"]
        save_data(data)

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

async def schedule(update: Update, context: CallbackContext):
    """Обрабатывает команду /schedule."""
    args = context.args  # Получаем аргументы команды
    if len(args) < 3:
        await update.message.reply_text(
            "Некорректный формат. Используйте:\n"
            "`/schedule @username день предмет время1 время2 ...`\n\n"
            "Пример:\n"
            "`/schedule @ivan123 Понедельник Английский 10:00 14:00`",
            parse_mode="Markdown"
        )
        return

    # Парсинг аргументов команды
    username, day, subject, *times = args
    if not times:
        await update.message.reply_text("Укажите хотя бы одно время.")
        return

    # Загружаем данные
    data = load_data()

    # Проверяем, есть ли пользователь
    user_id = None
    for uid, user_info in data["users"].items():
        if user_info.get("username") == username.lstrip('@'):
            user_id = uid
            break

    if not user_id:
        await update.message.reply_text(f"Пользователь {username} не найден.")
        return

    # Добавляем расписание
    entry = {"day": day, "description": subject, "time": ", ".join(times)}
    if user_id not in data["schedule"]:
        data["schedule"][user_id] = []
    data["schedule"][user_id].append(entry)
    save_data(data)

    await update.message.reply_text(f"Расписание для {username} обновлено:\n{day} {', '.join(times)} - {subject}")

async def unknown_command(update: Update, _):
    await update.message.reply_text("Неизвестная команда.")

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

async def edit_schedule(update: Update, _):
    """Функция редактирования расписания."""
    await update.message.reply_text("Функция редактирования расписания пока в разработке.")

async def handle_admin_button(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопок администратора."""
    user = update.effective_user

    # Проверяем, является ли пользователь администратором
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для использования этой функции.")
        return

    # Обработка текста кнопок
    text = update.message.text

    if text == "Добавить расписание":
        await update.message.reply_text(
            "Для добавления расписания используйте команду:\n\n"
            "`/schedule @username день предмет время1 время2 ...`\n\n"
            "Пример:\n"
            "`/schedule @ivan123 Понедельник Английский 10:00 14:00`",
            parse_mode="Markdown"
        )
    elif text == "Ученики":
        await students(update, context)
    elif text == "Просмотр расписания всех":
        await view_all_schedules(update, context)
    elif text == "Редактировать расписание":
        await edit_schedule(update, context)
    elif text == "Сбросить к стандартному":
        reset_to_standard_schedule()
        await update.message.reply_text("Расписание сброшено к стандартному.")
    else:
        await update.message.reply_text("Неизвестная команда.")


# --- Основная функция ---
def main():
    """Запуск бота."""
    init_json_db()

    application = Application.builder().token(BOT_TOKEN).build()

    # Планировщик задач
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reset_to_standard_schedule,
        CronTrigger(day_of_week="sat", hour=23, minute=59)  # Сброс каждую субботу
    )
    scheduler.start()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_button))
    application.add_handler(CommandHandler("schedule", schedule))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logging.info("Бот запущен.")
    application.run_polling()

if __name__ == "__main__":
    main()
