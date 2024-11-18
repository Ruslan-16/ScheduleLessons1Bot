import os
import json
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
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
    """Создаёт файл базы данных, если его нет, с корректной структурой."""
    if not os.path.exists(JSON_DB_PATH):
        logging.info("Создаю файл базы данных users.json...")
        with open(JSON_DB_PATH, 'w') as f:
            json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)
    else:
        # Проверяем, что файл корректен
        load_data()


# Сохранение данных в JSON-файл
def save_data(data):
    """Сохраняет данные в файл базы."""
    with open(JSON_DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)


# Загрузка данных из JSON-файла
def load_data():
    """Загружает данные из базы и проверяет структуру."""
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()

    with open(JSON_DB_PATH, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            logging.error("Ошибка чтения файла users.json. Восстанавливаю базу.")
            data = {"users": {}, "schedule": {}, "standard_schedule": {}}
            save_data(data)
            return data

    # Проверка структуры данных
    if not isinstance(data, dict):
        logging.warning("Некорректная структура файла. Восстанавливаю базу.")
        data = {"users": {}, "schedule": {}, "standard_schedule": {}}
        save_data(data)
        return data

    # Проверка ключей в структуре данных
    for key in ["users", "schedule", "standard_schedule"]:
        if key not in data or not isinstance(data[key], dict):
            logging.warning(f"Ключ {key} отсутствует или некорректен. Исправляю.")
            data[key] = {}

    save_data(data)  # Обновляем файл, если были исправления
    return data


# Добавление пользователя
def add_user(user_id, username, first_name):
    """Добавляет пользователя в базу."""
    data = load_data()
    data["users"][str(user_id)] = {
        "username": username,
        "first_name": first_name
    }
    save_data(data)


# Команда /start
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user = update.effective_user
    logging.info(f"Пользователь {user.first_name} ({user.username}) отправил /start.")

    # Добавляем пользователя в базу данных
    add_user(user.id, user.username, user.first_name)

    if user.id == ADMIN_ID:
        # Клавиатура для администратора
        admin_keyboard = [
            ["Добавить расписание"],
            ["Ученики", "Редактировать расписание"],
            ["Сбросить к стандартному"]
        ]
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Выберите команду:",
            reply_markup=ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        )
    else:
        # Клавиатура для ученика
        user_keyboard = [["Мое расписание"]]
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=ReplyKeyboardMarkup(user_keyboard, resize_keyboard=True)
        )


# Обработка кнопок администратора
async def handle_admin_button(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопок администратора."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для использования этой функции.")
        return

    text = update.message.text

    if text == "Добавить расписание":
        await update.message.reply_text(
            "Для добавления расписания используйте команду в формате:\n"
            "/schedule @username день предмет время1 время2 ...\n\n"
            "Пример:\n"
            "/schedule @username Понедельник Математика 10:00 14:00 16:00"
        )
    elif text == "Ученики":
        await students(update, context)
    elif text == "Редактировать расписание":
        await update.message.reply_text("Эта функция пока в разработке.")
    elif text == "Сбросить к стандартному":
        await update.message.reply_text("Эта функция пока в разработке.")


# Команда /schedule для добавления расписания
async def schedule(update: Update, context: CallbackContext):
    """Добавляет расписание для ученика."""
    if len(context.args) < 4:
        await update.message.reply_text(
            "Использование: /schedule @username день предмет время1 время2 ...\n"
            "Пример: /schedule @username Понедельник Математика 10:00 14:00"
        )
        return

    username = context.args[0]
    day = context.args[1]
    description = context.args[2]
    times = context.args[3:]

    data = load_data()
    user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)

    if not user_id:
        await update.message.reply_text(f"Пользователь @{username} не найден.")
        return

    data["schedule"].setdefault(user_id, [])

    for time in times:
        data["schedule"][user_id].append({
            "day": day,
            "time": time,
            "description": description,
            "reminder_sent_1h": False,
            "reminder_sent_24h": False
        })

    save_data(data)
    await update.message.reply_text(f"Расписание для @{username} успешно добавлено.")


# Команда /students для отображения всех учеников
async def students(update: Update, context: CallbackContext):
    """Отображает список всех учеников."""
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for user_id, info in data["users"].items():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)


# Команда /my_schedule для просмотра расписания учеником
async def my_schedule(update: Update, context: CallbackContext):
    """Отображает расписание ученика."""
    user_id = str(update.effective_user.id)
    data = load_data()

    if user_id in data["schedule"]:
        schedule_text = "Ваше расписание:\n"
        for entry in data["schedule"][user_id]:
            schedule_text += f"{entry['day']} {entry['time']} - {entry['description']}\n"
        await update.message.reply_text(schedule_text)
    else:
        await update.message.reply_text("Ваше расписание пусто.")


# Основная функция
def main():
    """Запускает бота."""
    logging.info("Инициализация бота...")
    init_json_db()

    application = Application.builder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.start()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("schedule", schedule))
    application.add_handler(CommandHandler("my_schedule", my_schedule))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_button))

    logging.info("Бот запущен и готов к работе!")
    application.run_polling()


if __name__ == "__main__":
    main()
