import os
import json
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters
import pytz
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
days_translation = {
    "Monday": "Понедельник",
    "Tuesday": "Вторник",
    "Wednesday": "Среда",
    "Thursday": "Четверг",
    "Friday": "Пятница",
    "Saturday": "Суббота",
    "Sunday": "Воскресенье"
}
user_data = {}  # Пустой словарь для хранения username -> chat_id
# Устанавливаем временную зону для Москвы
local_tz = pytz.timezone('Europe/Moscow')

# Получаем текущее время в московской временной зоне
now = datetime.now(local_tz)
print(f"Текущее московское время: {now}")

# Пример: преобразование времени занятия
lesson_time_str = "10:00"  # Время занятия в локальном времени
lesson_date = datetime.strptime(lesson_time_str, "%H:%M")

# Локализуем время занятия в московской зоне
lesson_datetime = local_tz.localize(lesson_date)
print(f"Время занятия с локализацией: {lesson_datetime}")

async def get_my_id(update: Update, context: CallbackContext):
    """Возвращает chat_id пользователя."""
    await update.message.reply_text(f"ADMIN_ID: {update.effective_chat.id}")

async def send_reminders(application):
    """Проверяет расписание и отправляет напоминания ученикам."""
    now = datetime.now()
    reminders_sent = []

    for user_name, lessons in temporary_schedule.items():
        for lesson in lessons:
            try:
                # Разбираем строку расписания
                day, time_details = lesson.split(" ", 1)
                lesson_time_str = time_details.split(" - ")[0]
                lesson_time = datetime.strptime(lesson_time_str, "%H:%M").time()

                # Определяем дату занятия
                current_day = days_translation[now.strftime("%A")]
                days_to_lesson = (list_days.index(day) - list_days.index(current_day)) % 7
                lesson_date = (now + timedelta(days=days_to_lesson)).date()
                lesson_datetime = datetime.combine(lesson_date, lesson_time)

                # Напоминания
                reminder_1h_before = lesson_datetime - timedelta(hours=1)
                reminder_24h_before = lesson_datetime - timedelta(days=1)

                # Проверяем напоминания
                if reminder_1h_before <= now < lesson_datetime:
                    chat_id = user_data.get(user_name)  # Находим chat_id по username
                    if chat_id:
                        await application.bot.send_message(chat_id=chat_id, text=f"Напоминание: у вас занятие через 1 час.\n{lesson}")
                        reminders_sent.append((user_name, "1 час"))
                elif reminder_24h_before <= now < reminder_1h_before:
                    chat_id = user_data.get(user_name)  # Находим chat_id по username
                    if chat_id:
                        await application.bot.send_message(chat_id=chat_id, text=f"Напоминание: у вас занятие через 24 часа.\n{lesson}")
                        reminders_sent.append((user_name, "24 часа"))
            except Exception as e:
                print(f"Ошибка обработки занятия для {user_name}: {lesson}. Ошибка: {e}")

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
    user_id = update.effective_chat.id  # chat_id пользователя
    user_name = update.effective_chat.username  # username пользователя

    # Если username отсутствует
    if not user_name:
        await update.message.reply_text(
            "У вас не установлен username в Telegram. Пожалуйста, добавьте username в настройках Telegram и повторите попытку."
        )
        return

    # Добавляем администратора в user_data (если его нет)
    if user_id == ADMIN_ID:
        if user_name not in user_data:
            user_data[user_name] = user_id
        await update.message.reply_text(
            "Добро пожаловать, администратор! Выберите действие:",
            reply_markup=get_main_menu(is_admin=True)
        )
        return

    # Проверяем, есть ли username в расписании
    if user_name not in temporary_schedule:
        await update.message.reply_text(
            "Извините, вас нет в расписании. Свяжитесь с администратором, если это ошибка."
        )
        return

    # Регистрируем пользователя
    user_data[user_name] = user_id  # Связываем username с chat_id
    print(f"[DEBUG] User data: {user_data}")
    print(f"[DEBUG] Registered users: {list(user_data.keys())}")

    # Ответ пользователю
    await update.message.reply_text(
        "Добро пожаловать! Ваше расписание готово. Выберите действие:",
        reply_markup=get_main_menu(False)
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

    if not user_data:
        await update.message.reply_text("Список зарегистрированных пользователей пуст.")
    else:
        # Формируем сообщение со списком зарегистрированных пользователей
        message = "\n".join([f"@{username}" for username in user_data.keys()])
        await update.message.reply_text(f"Список зарегистрированных пользователей:\n{message}")

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
    app.add_handler(CommandHandler("get_my_id", get_my_id))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
