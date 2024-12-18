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
BOT_TOKEN= "7843267156:AAHGuD8B4GAY73ECvkGWnoDIIQMrD6GCsLc"
ADMIN_ID= 413537120
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Ruslan-16/ScheduleLessons1Bot/refs/heads/main/users.json"

# --- Глобальные переменные ---
temporary_schedule = {}  # Хранение оперативного расписания
registered_users = []  # Список зарегистрированных пользователей
list_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

async def send_reminders(application):
    """Проверяет расписание и отправляет напоминания ученикам."""
    now = datetime.now()  # Текущее время
    reminders_sent = []  # Для отладки, чтобы понять, кому отправлены напоминания
    # Обходим каждого зарегистрированного ученика
    for user_name, lessons in temporary_schedule.items():
        for lesson in lessons:
            try:
                # Извлекаем день недели и время из строки занятия
                day, time_details = lesson.split(" ", 1)
                lesson_time_str = time_details.split(" - ")[0]  # Извлекаем только время
                lesson_time = datetime.strptime(lesson_time_str, "%H:%M").time()  # Преобразуем в объект времени
                # Определяем дату следующего занятия
                current_day = datetime.now().strftime("%A")  # Сегодняшний день недели
                days_to_lesson = (list_days.index(day) - list_days.index(current_day)) % 7
                lesson_date = (now + timedelta(days=days_to_lesson)).date()
                lesson_datetime = datetime.combine(lesson_date, lesson_time)  # Полная дата и время занятия
                # Время для напоминания
                reminder_1h_before = lesson_datetime - timedelta(hours=1)
                reminder_24h_before = lesson_datetime - timedelta(days=1)
                # Проверяем, нужно ли отправить напоминание
                if now >= reminder_1h_before and now < lesson_datetime:
                    await application.bot.send_message(chat_id=user_name, text=f"Напоминание: у вас занятие через 1 час.\n{lesson}")
                    reminders_sent.append((user_name, "1 час"))
                elif now >= reminder_24h_before and now < reminder_1h_before:
                    await application.bot.send_message(chat_id=user_name, text=f"Напоминание: у вас занятие через 24 часа.\n{lesson}")
                    reminders_sent.append((user_name, "24 часа"))
            except Exception as e:
                print(f"Ошибка обработки занятия для {user_name}: {lesson}. Ошибка: {e}")
    # Отладочный вывод для проверки
    print(f"[DEBUG] Напоминания отправлены: {reminders_sent}")
# --- Функции загрузки расписания ---
def load_default_schedule():
    """Загружает расписание с GitHub."""
    try:
        github_raw_url = GITHUB_RAW_URL.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        response = requests.get(github_raw_url)
        response.raise_for_status()
        schedule = response.json()
        print(f"Расписание успешно загружено: {schedule}")  # Отладочный вывод
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
    print("Текущее расписание после сброса:", temporary_schedule)  # Отладочный вывод

# --- Функции обработки команд ---
async def start(update: Update, context: CallbackContext):
    """Обработка команды /start."""
    user_id = update.effective_chat.id
    user_name = update.effective_chat.username  # Используем username
    # Проверяем, есть ли username
    if not user_name:
        await update.message.reply_text(
            "У вас не установлен username в Telegram. Пожалуйста, добавьте username в настройках Telegram и повторите попытку."
        )
        return
    # Проверяем, есть ли username пользователя в расписании
    if user_name not in temporary_schedule:
        await update.message.reply_text(
            "Извините, вас нет в расписании. Свяжитесь с администратором, если это ошибка."
        )
        return
    # Добавляем пользователя в список зарегистрированных (если его нет)
    if user_name not in registered_users:
        registered_users.append(user_name)
    # Отладочный вывод для проверки
    print(f"[DEBUG] Registered users: {registered_users}")
    print(f"[DEBUG] Current schedule: {temporary_schedule}")

    # Отправляем клавиатуру
    is_admin = user_id == ADMIN_ID
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=get_main_menu(is_admin)
    )

async def view_schedule(update: Update, context: CallbackContext):
    """Показывает расписание для конкретного ученика."""
    user_name = update.effective_chat.username  # Используем username вместо first_name
    user_schedule = temporary_schedule.get(user_name)

    if user_schedule:
        message = "\n".join(user_schedule)
        await update.message.reply_text(f"Ваше расписание:\n{message}")
    else:
        await update.message.reply_text("У вас нет расписания. Пожалуйста, свяжитесь с администратором.")

async def view_students(update: Update, context: CallbackContext):
    """Показывает список всех зарегистрированных пользователей (только для администратора)."""
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if not registered_users:
        await update.message.reply_text("Список зарегистрированных пользователей пуст.")
    else:
        await update.message.reply_text("Список зарегистрированных пользователей:\n" + "\n".join(registered_users))

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
    """Создаёт меню клавиатуры."""
    if is_admin:
        # Кнопки для администратора
        buttons = [
            [KeyboardButton("Просмотреть всё расписание")],
            [KeyboardButton("Редактировать расписание"), KeyboardButton("Сбросить расписание")],
            [KeyboardButton("Ученики")]
        ]
    else:
        # Кнопки для ученика
        buttons = [[KeyboardButton("Моё расписание")]]
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
    elif text == "Редактировать расписание" and user_id == ADMIN_ID:
        await update.message.reply_text("Для редактирования используйте команду /add_schedule.")
    elif text == "Ученики" and user_id == ADMIN_ID:
        await view_students(update, context)
    else:
        # Обработка неизвестной команды
        await update.message.reply_text("Неизвестная команда. Пожалуйста, используйте кнопки.")

# --- Планировщик задач ---
def schedule_jobs(application: Application):
    """Настраивает планировщик задач."""
    scheduler = BackgroundScheduler()
    # Задача: проверять расписание каждые 30 минут
    scheduler.add_job(
        send_reminders,
        trigger="interval",
        minutes=30,
        args=[application]
    )
    # Задача: сбрасывать расписание каждую субботу в 23:00
    scheduler.add_job(reset_schedule, CronTrigger(day_of_week="sat", hour=23, minute=0))
    scheduler.start()
    print("Планировщик задач запущен.")
# --- Главная функция ---
def main():
    global temporary_schedule
    reset_schedule()  # Загружаем расписание с GitHub

    app = Application.builder().token(BOT_TOKEN).build()

    # Настраиваем планировщик
    schedule_jobs(app)

    # Регистрируем команды и обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("view_all", view_all))
    app.add_handler(CommandHandler("add_schedule", add_schedule))
    app.add_handler(CommandHandler("reset", manual_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
