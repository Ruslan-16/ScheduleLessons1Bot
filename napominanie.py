import os
import json
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import shutil

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Загружаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
JSON_DB_PATH = os.getenv("JSON_DB_PATH", "users.json")
scheduler = AsyncIOScheduler()

# Проверяем переменные окружения
if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
if ADMIN_ID == 0:
    raise ValueError("Переменная окружения ADMIN_ID не установлена или равна 0!")

# --- Вспомогательные функции ---
def init_json_db():
    """Создаёт файл базы данных, если его нет."""
    try:
        if not os.path.exists(JSON_DB_PATH):
            logging.info(f"Создаю файл базы данных {JSON_DB_PATH}...")
            with open(JSON_DB_PATH, 'w') as f:
                json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)
    except Exception as e:
        logging.error(f"Ошибка при создании базы данных: {e}")


def backup_json_file():
    """Создаёт резервную копию файла данных."""
    try:
        backup_path = f"{JSON_DB_PATH}.backup"
        if os.path.exists(JSON_DB_PATH):
            shutil.copy(JSON_DB_PATH, backup_path)
            logging.info(f"Резервная копия создана: {backup_path}")
    except Exception as e:
        logging.error(f"Ошибка при создании резервной копии: {e}")


def load_data():
    """Загружает данные из JSON-файла."""
    try:
        if not os.path.exists(JSON_DB_PATH):
            init_json_db()
        with open(JSON_DB_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        logging.error("Ошибка чтения базы данных. Восстанавливаю базу.")
        init_json_db()
        return {"users": {}, "schedule": {}, "standard_schedule": {}}


def save_data(data):
    """Сохраняет данные в JSON-файл."""
    try:
        backup_json_file()  # Создаём резервную копию перед записью
        with open(JSON_DB_PATH, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Ошибка записи базы данных: {e}")


# --- Обработка кнопок ---
async def handle_admin_button(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопок администратора."""
    user = update.effective_user

    # Проверяем, что пользователь — администратор
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для использования этой функции.")
        return

    # Текст кнопки
    text = update.message.text
    logging.info(f"Обработана кнопка: {text}")

    if text == "Добавить расписание":
        await update.message.reply_text(
            "Для добавления расписания используйте команду в формате:\n"
            "/schedule @username день предмет время1 время2 ...\n\n"
            "Пример:\n"
            "/schedule @ivan123 Понедельник Математика 10:00 14:00"
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


# --- Основные функции ---
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user = update.effective_user
    logging.info(f"Пользователь {user.first_name} ({user.username}) с ID {user.id} вызвал /start.")

    # Добавляем пользователя
    data = load_data()
    data["users"][str(user.id)] = {
        "username": user.username,
        "first_name": user.first_name
    }
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


async def view_all_schedules(update: Update, context: CallbackContext):
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


async def edit_schedule(update: Update, context: CallbackContext):
    """Функция редактирования расписания."""
    await update.message.reply_text("Функция редактирования расписания пока в разработке.")


def reset_to_standard_schedule():
    """Сбрасывает расписание на стандартное."""
    data = load_data()
    if "standard_schedule" in data:
        data["schedule"] = data["standard_schedule"].copy()
        save_data(data)
        logging.info("Расписание сброшено к стандартному.")
    else:
        logging.warning("Стандартное расписание не задано.")


# --- Основная функция ---
def main():
    """Запуск бота."""
    init_json_db()  # Инициализация базы данных
    application = Application.builder().token(BOT_TOKEN).build()

    scheduler.add_job(reset_to_standard_schedule, CronTrigger(day_of_week="sat", hour=23, minute=59))
    scheduler.start()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("view_all_schedules", view_all_schedules))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_button))

    logging.info("Бот запущен.")
    application.run_polling()


if __name__ == "__main__":
    main()
