import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, ChatMemberHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Загружаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    logging.error("Переменная окружения BOT_TOKEN не установлена!")
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
if not ADMIN_ID:
    logging.error("Переменная окружения ADMIN_ID не установлена!")
    raise ValueError("Переменная окружения ADMIN_ID не установлена!")

ADMIN_ID = int(ADMIN_ID)
JSON_DB_PATH = "users.json"  # Путь к JSON-файлу для хранения данных

# Инициализация JSON-базы данных
def init_json_db():
    if not os.path.exists(JSON_DB_PATH):
        logging.info("Создаю файл базы данных users.json...")
        with open(JSON_DB_PATH, 'w') as f:
            json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)

# Сохранение данных в JSON-файл
def save_data(data):
    with open(JSON_DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)

# Загрузка данных из JSON-файла
def load_data():
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()

    with open(JSON_DB_PATH, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            logging.error("Ошибка чтения файла users.json. Восстанавливаю базу.")
            data = {"users": {}, "schedule": {}, "standard_schedule": {}}

    # Проверяем, что загруженные данные — словарь
    if not isinstance(data, dict):
        data = {"users": {}, "schedule": {}, "standard_schedule": {}}

    return data

# Добавление пользователя
def add_user(user_id, username, first_name):
    data = load_data()
    data["users"][str(user_id)] = {
        "username": username,
        "first_name": first_name
    }
    save_data(data)

# Команда /start
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    logging.info(f"Пользователь {user.first_name} ({user.username}) отправил /start.")

    # Добавляем пользователя в базу данных
    add_user(user.id, user.username, user.first_name)

    if user.id == ADMIN_ID:
        # Сообщение для администратора
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Доступные команды:",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["Добавить расписание", "Установить стандартное расписание"],
                    ["Ученики", "Редактировать расписание"],
                    ["Сбросить к стандартному"]
                ],
                resize_keyboard=True
            )
        )
    else:
        # Сообщение для ученика
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=ReplyKeyboardMarkup(
                [["Мое расписание"]], resize_keyboard=True
            )
        )

# Команда для проверки работы
async def echo(update: Update, context: CallbackContext):
    await update.message.reply_text(f"Получено сообщение: {update.message.text}")

# Основная функция
def main():
    logging.info("Инициализация бота...")
    init_json_db()

    # Проверяем токен перед запуском
    if not BOT_TOKEN:
        raise ValueError("Токен не установлен в переменной окружения!")

    application = Application.builder().token(BOT_TOKEN).build()

    # Планировщик задач
    scheduler = AsyncIOScheduler()
    scheduler.start()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("echo", echo))

    # Запуск бота
    logging.info("Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == "__main__":
    main()
