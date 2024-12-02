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

def load_data():
    """Загружает данные из JSON-файла."""
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()
    with open(JSON_DB_PATH, 'r') as f:
        return json.load(f)

def save_data(data):
    """Сохраняет данные в JSON-файл."""
    with open(JSON_DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)
    logging.info(f"Данные успешно сохранены в {JSON_DB_PATH}")

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
    data = load_data()
    messages = []

    # Проверка наличия ключа schedule
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
                # Проверка формата времени
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

    # Сохранение данных
    save_data(data)
    logging.info(f"Данные успешно сохранены: {data}")

    # Отправляем сообщение, что расписание добавлено
    await update.message.reply_text("\n".join(messages))


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


async def reset_to_standard_schedule():
    """Сбрасывает расписание на стандартное."""
    data = load_data()
    if "standard_schedule" in data:
        data["schedule"] = data["standard_schedule"]
        save_data(data)

async def handle_admin_button(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопок администратора."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для использования этой функции.")
        return

    text = update.message.text
    if text == "Ученики":
        await students(update, context)
    elif text == "Добавить расписание":
        await add_schedule(update, context)
    elif text == "Просмотр расписания":
        await view_all_schedules(update, context)
    elif text == "Сбросить расписание":
        await reset_to_standard_schedule()
        await update.message.reply_text("Расписание сброшено к стандартному.")


async def add_schedule_for_students(update: Update, context: CallbackContext):
    """Добавляет расписание для нескольких учеников."""
    data = load_data()
    user = update.effective_user

    # Проверка на права администратора
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для использования этой функции.")
        return

    # Проверяем, что формат правильный
    if len(context.args) < 5:
        await update.message.reply_text(
            "Неверный формат. Пример использования: /schedule @username Понедельник Математика 10:00 14:00, @username2 Вторник Физика 9:00 12:00"
        )
        return

    # Итерируем по списку аргументов
    added_count = 0
    for i in range(0, len(context.args), 5):  # Шаг 5, чтобы обрабатывать блоки данных для каждого ученика
        if i + 4 >= len(context.args):
            break  # Не хватает данных для обработки

        username = context.args[i]  # @username
        day = context.args[i + 1]  # День недели (например, Понедельник)
        subject = context.args[i + 2]  # Название предмета (например, Математика)
        start_time = context.args[i + 3]  # Время начала (например, 10:00)
        end_time = context.args[i + 4]  # Время конца (например, 14:00)

        # Находим ученика по username
        student = None
        for user_id, info in data["users"].items():
            if info["username"] == username:
                student = user_id
                break

        if not student:
            await update.message.reply_text(f"Ученик с username @{username} не найден.")
            continue

        # Добавляем расписание
        schedule_entry = {
            "day": day,
            "subject": subject,
            "time": f"{start_time} - {end_time}",
            "description": f"{subject} ({start_time} - {end_time})"
        }

        # Обновляем расписание для этого ученика
        if student not in data["schedule"]:
            data["schedule"][student] = []

        data["schedule"][student].append(schedule_entry)
        added_count += 1

    # Сохраняем данные
    save_data(data)

    # Ответ пользователю
    if added_count > 0:
        await update.message.reply_text(f"Добавлено {added_count} расписаний.")
    else:
        await update.message.reply_text("Не удалось добавить расписания. Пожалуйста, проверьте ввод.")


# --- Основная функция ---
def main():
    init_json_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_button))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("view_all_schedules", view_all_schedules))
    application.add_handler(CommandHandler("schedule", add_schedule_for_students))

    logging.info("Бот запущен.")
    application.run_polling()

if __name__ == "__main__":
    main()
