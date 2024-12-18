import os
import json
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, filters
from dotenv import load_dotenv

load_dotenv()
# --- Переменные окружения ---
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен бота из переменной окружения
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ID администратора
GITHUB_RAW_URL = "https://github.com/Ruslan-16/ScheduleLessons1Bot/blob/main/users.json"  # Ссылка на default расписание
DEFAULT_SCHEDULE_FILE = "users.json"  # Локальный файл для хранения стандартного расписания

# --- Глобальные переменные ---
temporary_schedule = {}  # Оперативное расписание

# --- Функции для загрузки и сохранения расписания ---
def load_default_schedule():
    """Загрузить стандартное расписание с GitHub."""
    try:
        response = requests.get(GITHUB_RAW_URL)
        if response.status_code == 200:
            with open(DEFAULT_SCHEDULE_FILE, "w", encoding="utf-8") as file:
                file.write(response.text)
            return json.loads(response.text)
        else:
            print("Ошибка при загрузке расписания с GitHub")
    except Exception as e:
        print(f"Ошибка: {e}")
    return {}

def reset_schedule():
    """Сброс расписания к стандартному."""
    global temporary_schedule
    temporary_schedule = load_default_schedule()
    print("Расписание сброшено к стандартному.")

# --- Обработчики команд ---
async def start(update: Update, context: CallbackContext):
    user_id = str(update.effective_chat.id)
    if user_id not in temporary_schedule:
        temporary_schedule[user_id] = []
    await update.message.reply_text("Добро пожаловать! Ваше расписание настроено. Используйте кнопки для управления.")

async def view_schedule(update: Update, context: CallbackContext):
    user_id = str(update.effective_chat.id)
    user_schedule = temporary_schedule.get(user_id, ["У вас нет занятий."])
    message = "\n".join(user_schedule)
    await update.message.reply_text(f"Ваше расписание:\n{message}")


async def add_schedule(update: Update, context: CallbackContext):
    """Добавляет или изменяет расписание конкретного пользователя."""
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        # Разбираем аргументы команды
        user_id = context.args[0]  # Имя ученика (ключ в расписании)
        lesson = " ".join(context.args[1:])  # Остальные аргументы - это день, время и занятие

        if not lesson:
            await update.message.reply_text("Ошибка: укажите день, время и занятие!")
            return

        # Добавляем или обновляем расписание ученика
        if user_id in temporary_schedule:
            temporary_schedule[user_id].append(lesson)
        else:
            temporary_schedule[user_id] = [lesson]

        await update.message.reply_text(f"Расписание для {user_id} обновлено:\n{lesson}")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование команды:\n/add_schedule user_id день время - занятие")


async def view_all(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    message = "\n\n".join([f"{user}: {', '.join(lessons)}" for user, lessons in temporary_schedule.items()])
    await update.message.reply_text(f"Все расписание:\n{message}")

async def manual_reset(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    reset_schedule()
    await update.message.reply_text("Расписание успешно сброшено к стандартному.")

# --- Планировщик задач ---
def schedule_jobs(application: Application):
    scheduler = BackgroundScheduler()
    # Сброс расписания каждую субботу в 23:00
    scheduler.add_job(reset_schedule, CronTrigger(day_of_week="sat", hour=23, minute=0))
    scheduler.start()
    print("Планировщик задач запущен.")

# --- Главное меню кнопок ---
def get_main_menu(is_admin=False):
    buttons = [
        [KeyboardButton("Моё расписание")],
    ]
    if is_admin:
        buttons.append([KeyboardButton("Просмотреть всё расписание"), KeyboardButton("Сбросить расписание")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def menu(update: Update, context: CallbackContext):
    is_admin = update.effective_chat.id == ADMIN_ID
    await update.message.reply_text("Выберите действие:", reply_markup=get_main_menu(is_admin))

# --- Обработчик сообщений ---
async def button_handler(update: Update, context: CallbackContext):
    text = update.message.text
    user_id = update.effective_chat.id
    if text == "Моё расписание":
        await view_schedule(update, context)
    elif text == "Просмотреть всё расписание" and user_id == ADMIN_ID:
        await view_all(update, context)
    elif text == "Сбросить расписание" and user_id == ADMIN_ID:
        await manual_reset(update, context)

# --- Главная функция ---
def main():
    global temporary_schedule
    # Загрузить стандартное расписание при старте
    temporary_schedule = load_default_schedule()

    # Инициализация бота
    app = Application.builder().token(BOT_TOKEN).build()
    # Планировщик задач
    schedule_jobs(app)

    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_schedule", add_schedule))
    app.add_handler(CommandHandler("view_all", view_all))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("reset", manual_reset))

    # Обработчик кнопок
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    # Запуск бота
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
