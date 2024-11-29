import os
import json
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Загружаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
JSON_DB_PATH = os.getenv("JSON_DB_PATH", "users.json")
scheduler = AsyncIOScheduler()

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
        with open(JSON_DB_PATH, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Ошибка записи базы данных: {e}")


# --- Команды ---
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


async def schedule(update: Update, context: CallbackContext):
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

    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 4:
            messages.append(f"Ошибка: недостаточно данных в строке: {line}")
            continue

        username, day, subject, *times = parts

        # Проверяем день недели
        if day not in valid_days:
            messages.append(f"Ошибка: некорректный день недели: {day}")
            continue

        # Проверяем формат времени
        for time in times:
            try:
                datetime.strptime(time, "%H:%M")
            except ValueError:
                messages.append(f"Ошибка: некорректный формат времени: {time}")
                continue

        # Проверяем пользователя
        user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)
        if not user_id:
            messages.append(f"Ошибка: пользователь {username} не найден.")
            continue

        # Добавляем расписание
        data["schedule"].setdefault(user_id, [])
        for time in times:
            data["schedule"][user_id].append({
                "day": day,
                "time": time,
                "description": subject,
                "reminder_sent_1h": False,
                "reminder_sent_24h": False
            })

        messages.append(f"Добавлено: {username} - {day} - {subject} в {', '.join(times)}")

    save_data(data)
    await update.message.reply_text("\n".join(messages))


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
    application.add_handler(CommandHandler("schedule", schedule))

    logging.info("Бот запущен.")
    application.run_polling()


if __name__ == "__main__":
    main()
