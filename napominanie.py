import os
import json
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters

# Загрузка переменных окружения
load_dotenv()

# --- Переменные окружения ---
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен бота
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ID администратора
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Ruslan-16/ScheduleLessons1Bot/main/users.json"  # URL расписания

# --- Глобальные переменные ---
temporary_schedule = {}  # Хранение оперативного расписания


# --- Функции загрузки расписания ---
def load_default_schedule():
    """Загружает расписание с GitHub."""
    try:
        github_raw_url = GITHUB_RAW_URL.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        response = requests.get(github_raw_url)
        response.raise_for_status()
        schedule = response.json()
        print(f"Расписание успешно загружено: {schedule}")
        return schedule
    except requests.RequestException as e:
        print(f"Ошибка загрузки расписания с GitHub: {e}")
        return {}
    except json.JSONDecodeError:
        print("Ошибка: Файл расписания не является валидным JSON.")
        return {}


def reset_schedule():
    """Сбрасывает расписание к стандартному."""
    global temporary_schedule
    temporary_schedule = load_default_schedule()
    print("Текущее расписание сброшено:", temporary_schedule)


# --- Функции обработки команд ---
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    is_admin = update.effective_chat.id == ADMIN_ID
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=get_main_menu(is_admin)
    )


async def view_schedule(update: Update, context: CallbackContext):
    """Показывает расписание для конкретного ученика."""
    user_name = update.effective_chat.first_name  # Имя пользователя из Telegram
    user_schedule = temporary_schedule.get(user_name)  # Ищем расписание по имени пользователя

    if user_schedule:
        message = "\n".join(user_schedule)
        await update.message.reply_text(f"Ваше расписание:\n{message}")
    else:
        await update.message.reply_text("У вас нет расписания. Проверьте, правильно ли указаны ваши данные в системе.")


async def view_all(update: Update, context: CallbackContext):
    """Показывает всё расписание (только для администратора)."""
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if not temporary_schedule:
        await update.message.reply_text("Расписание пустое или не загружено.")
        return

    message = "\n\n".join([
        f"{user}:\n" + "\n".join(lessons)
        for user, lessons in temporary_schedule.items()
    ])
    await update.message.reply_text(f"Все расписание:\n\n{message}")


async def manual_reset(update: Update, context: CallbackContext):
    """Ручной сброс расписания (только для администратора)."""
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    reset_schedule()
    await update.message.reply_text("Расписание успешно сброшено к стандартному.")


async def add_schedule(update: Update, context: CallbackContext):
    """Добавляет или изменяет расписание конкретного пользователя (только для администратора)."""
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        user_id = context.args[0]  # Имя ученика
        lesson = " ".join(context.args[1:])  # Остальные аргументы - это расписание
        if not lesson:
            await update.message.reply_text("Ошибка: укажите расписание!")
            return

        if user_id in temporary_schedule:
            temporary_schedule[user_id].append(lesson)
        else:
            temporary_schedule[user_id] = [lesson]

        await update.message.reply_text(f"Расписание для {user_id} обновлено:\n{lesson}")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование команды:\n/add_schedule user_id день время - занятие")


# --- Кнопки меню ---
def get_main_menu(is_admin=False):
    """Возвращает меню для пользователя."""
    buttons = [[KeyboardButton("Моё расписание")]]
    if is_admin:
        buttons.append([
            KeyboardButton("Просмотреть всё расписание"),
            KeyboardButton("Редактировать расписание"),
            KeyboardButton("Сбросить расписание")
        ])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


# --- Обработчик кнопок ---
async def button_handler(update: Update, context: CallbackContext):
    """Обрабатывает действия при нажатии кнопок."""
    user_id = update.effective_chat.id
    text = update.message.text

    if text == "Моё расписание":
        await view_schedule(update, context)
    elif text == "Просмотреть всё расписание" and user_id == ADMIN_ID:
        await view_all(update, context)
    elif text == "Сбросить расписание" and user_id == ADMIN_ID:
        reset_schedule()
        await update.message.reply_text("Расписание успешно сброшено.")
    else:
        await update.message.reply_text("Неизвестная команда. Пожалуйста, используйте кнопки.")


# --- Планировщик задач ---
def schedule_jobs():
    """Настраивает планировщик задач."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(reset_schedule, CronTrigger(day_of_week="sat", hour=23, minute=0))
    scheduler.start()
    print("Планировщик задач запущен.")


# --- Главная функция ---
def main():
    global temporary_schedule
    temporary_schedule = load_default_schedule()

    app = Application.builder().token(BOT_TOKEN).build()

    # Планировщик
    schedule_jobs()

    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("view_all", view_all))
    app.add_handler(CommandHandler("add_schedule", add_schedule))
    app.add_handler(CommandHandler("reset", manual_reset))

    # Обработчик текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
