import os
import json
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
            data = {"users": {}, "schedule": {}, "standard_schedule": {}}

    # Проверяем, что структура данных корректна
    for key in ["users", "schedule", "standard_schedule"]:
        if key not in data:
            data[key] = {}

    return data

# Добавление пользователя
def add_user(user_id, username, first_name):
    data = load_data()
    if "users" not in data:
        data["users"] = {}

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
                continue  # Пропускаем некорректные записи
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
    add_user(user.id, user.username, user.first_name)

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Доступные команды:",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["Добавить расписание", "Установить стандартное расписание"],
                    ["Удалить расписание", "Редактировать расписание"],
                    ["Сбросить к стандартному"]
                ],
                resize_keyboard=True
            )
        )
    else:
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=ReplyKeyboardMarkup(
                [["Мое расписание"]], resize_keyboard=True
            )
        )

# Команда /edit_schedule
async def edit_schedule(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для редактирования расписания.")
        return

    if len(context.args) < 5:
        await update.message.reply_text(
            "Использование: /edit_schedule @username индекс_занятия день время описание\n"
            "Пример: /edit_schedule @ivan123 1 Понедельник 18:00 Новый предмет"
        )
        return

    username, index, day, time, *description = context.args
    description = " ".join(description)

    if not is_valid_time(time):
        await update.message.reply_text("Ошибка: время должно быть в формате ЧЧ:ММ (например, 15:30).")
        return

    data = load_data()
    user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)

    if not user_id:
        await update.message.reply_text(f"Пользователь @{username} не найден.")
        return

    index = int(index) - 1
    if user_id in data["schedule"]:
        if 0 <= index < len(data["schedule"][user_id]):
            data["schedule"][user_id][index] = {
                "day": day,
                "time": time,
                "description": description,
                "reminder_sent_1h": False,
                "reminder_sent_24h": False
            }
            save_data(data)
            await update.message.reply_text(f"Запись №{index + 1} для @{username} успешно изменена.")
        else:
            await update.message.reply_text(f"Индекс {index + 1} вне диапазона записей.")
    else:
        await update.message.reply_text(f"У пользователя @{username} нет расписания.")

# Основная функция
def main():
    init_json_db()
    application = Application.builder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(reset_to_standard_schedule, 'cron', day_of_week='sat', hour=23, minute=59)
    scheduler.add_job(send_reminders, 'interval', minutes=1, args=[application])
    scheduler.start()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("edit_schedule", edit_schedule))

    application.run_polling()

if __name__ == "__main__":
    main()

