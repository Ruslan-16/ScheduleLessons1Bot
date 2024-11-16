import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, ChatMemberHandler, MessageHandler, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Загружаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
if not ADMIN_ID:
    raise ValueError("Переменная окружения ADMIN_ID не установлена!")

ADMIN_ID = int(ADMIN_ID)
JSON_DB_PATH = "users.json"  # Путь к JSON-файлу для хранения данных

# Инициализация JSON-базы данных (создает файл, если его нет)
def init_json_db():
    if not os.path.exists(JSON_DB_PATH):
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

    # Убедимся, что ключи существуют
    for key in ["users", "schedule", "standard_schedule"]:
        if key not in data:
            data[key] = {}

    return data

# Добавление пользователя
def add_user(user_id, username, first_name):
    data = load_data()
    data["users"][str(user_id)] = {
        "username": username,
        "first_name": first_name
    }
    save_data(data)

# Установить стандартное расписание
def set_standard_schedule(user_id, day, time, description):
    data = load_data()
    user_id = str(user_id)
    if user_id not in data["standard_schedule"]:
        data["standard_schedule"][user_id] = []
    data["standard_schedule"][user_id].append({
        "day": day,
        "time": time,
        "description": description
    })
    save_data(data)

# Сброс расписания к стандартному
def reset_to_standard_schedule():
    data = load_data()
    for user_id, standard_entries in data.get("standard_schedule", {}).items():
        data["schedule"][user_id] = [
            {
                "day": entry["day"],
                "time": entry["time"],
                "description": entry["description"],
                "reminder_sent_1h": False,
                "reminder_sent_24h": False
            }
            for entry in standard_entries
        ]
    save_data(data)
    logging.info("Все расписания были сброшены к стандартным.")

# Проверка валидности времени
def is_valid_time(time_str):
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False

# Преобразование дня недели
def translate_day_to_english(day):
    days_map = {
        "Понедельник": "Monday",
        "Вторник": "Tuesday",
        "Среда": "Wednesday",
        "Четверг": "Thursday",
        "Пятница": "Friday",
        "Суббота": "Saturday",
        "Воскресенье": "Sunday"
    }
    return days_map.get(day, "Invalid")

# Напоминание о занятии
async def send_reminders(context: CallbackContext):
    data = load_data()
    now = datetime.now()
    for user_id, entries in data.get("schedule", {}).items():
        for entry in entries:
            day_time = f"{translate_day_to_english(entry['day'])} {entry['time']}"
            if "Invalid" in day_time:
                continue
            try:
                entry_time = datetime.strptime(day_time, "%A %H:%M")
            except ValueError:
                continue
            # За 24 часа
            if not entry["reminder_sent_24h"] and now + timedelta(hours=24) >= entry_time:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: через 24 часа - {entry['description']} в {entry['time']}."
                )
                entry["reminder_sent_24h"] = True
            # За 1 час
            if not entry["reminder_sent_1h"] and now + timedelta(hours=1) >= entry_time:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: через 1 час - {entry['description']} в {entry['time']}."
                )
                entry["reminder_sent_1h"] = True
    save_data(data)

# Команда /start
async def start(update: Update, context: CallbackContext):
    user = update.effective_user

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

# Команда /students для отображения всех учеников
async def students(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для просмотра списка учеников.")
        return

    data = load_data()
    students_text = "Список учеников:\n"
    for user_id, info in data["users"].items():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)

# Команда /my_schedule для просмотра расписания учеником
async def my_schedule(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    data = load_data()

    if user_id in data["schedule"]:
        schedule_text = "Ваше расписание:\n"
        for entry in data["schedule"][user_id]:
            schedule_text += f"{entry['day']} {entry['time']} - {entry['description']}\n"
        await update.message.reply_text(schedule_text)
    else:
        await update.message.reply_text("Ваше расписание пусто.")

# Обработчик удаления пользователей
async def handle_user_removal(update: Update, context: CallbackContext):
    chat_member = update.chat_member
    user_id = chat_member.from_user.id
    status = chat_member.new_chat_member.status

    # Используем строки для проверки статуса
    if status in ["left", "kicked"]:
        data = load_data()
        if str(user_id) in data["users"]:
            del data["users"][str(user_id)]
        if str(user_id) in data["schedule"]:
            del data["schedule"][str(user_id)]
        if str(user_id) in data["standard_schedule"]:
            del data["standard_schedule"][str(user_id)]
        save_data(data)
        logging.info(f"Пользователь {user_id} удалён из системы, так как покинул чат.")

# Основная функция
def main():
    init_json_db()
    application = Application.builder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(reset_to_standard_schedule, 'cron', day_of_week='sat', hour=23, minute=59)
    scheduler.add_job(send_reminders, 'interval', minutes=1, args=[application])
    scheduler.start()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("my_schedule", my_schedule))
    application.add_handler(ChatMemberHandler(handle_user_removal, ChatMemberHandler.CHAT_MEMBER))

    application.run_polling()

if __name__ == "__main__":
    main()
