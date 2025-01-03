import os
import sys
import json
import requests
from datetime import datetime, timedelta
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters
import pytz
import logging
import signal
import asyncio
# Загрузка переменных окружения
load_dotenv()
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)
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
# Время сервера
server_time = datetime.now()
print(f"Серверное время: {server_time}")
# Московское время
moscow_tz = pytz.timezone('Europe/Moscow')
moscow_time = datetime.now(moscow_tz)
print(f"Московское время: {moscow_time}")
# Устанавливаем временную зону для Москвы
local_tz = pytz.timezone('Europe/Moscow')
# Получаем текущее время в московской временной зоне
now = datetime.now(local_tz)
print(f"Текущее московское время: {now}")

async def get_my_id(update: Update, context: CallbackContext):
    """Возвращает chat_id пользователя."""
    await update.message.reply_text(f"ADMIN_ID: {update.effective_chat.id}")

sent_reminders = set()

async def send_reminders(application):
    """Отправляет напоминания за 1 и за 24 часа до занятий."""
    await update_user_data()  # Обновляем список зарегистрированных пользователей перед отправкой напоминаний

    now = datetime.now(local_tz)  # Текущее время в московской зоне
    global sent_reminders  # Используем глобальную переменную для хранения отправленных напоминаний

    print(f"[DEBUG] send_reminders запущен в {now}")

    for user_name, lessons in temporary_schedule.items():
        # Проверяем, зарегистрирован ли пользователь
        if user_name not in user_data:
            print(f"[DEBUG] Пользователь {user_name} не зарегистрирован. Пропускаем.")
            continue

        # Получаем chat_id пользователя
        chat_id = user_data[user_name]

        for lesson in lessons:
            try:
                # Извлекаем данные из урока
                day = lesson['day']
                time_str = lesson['time']
                description = lesson.get('description', '')

                # Определяем ближайшую дату занятия
                current_day = days_translation[now.strftime("%A")]  # Сегодняшний день недели
                lesson_day_index = list_days.index(day)  # Индекс дня занятия
                current_day_index = list_days.index(current_day)  # Индекс текущего дня

                # Рассчитываем ближайшую дату занятия
                if lesson_day_index == current_day_index:
                    # Занятие сегодня
                    lesson_date = now.date()
                    if now.time() > datetime.strptime(time_str, "%H:%M").time():
                        # Если занятие уже прошло, переносим его на следующую неделю
                        lesson_date += timedelta(days=7)
                elif lesson_day_index > current_day_index:
                    # Занятие позже на этой неделе
                    days_to_lesson = lesson_day_index - current_day_index
                    lesson_date = now.date() + timedelta(days=days_to_lesson)
                else:
                    # Занятие на следующей неделе
                    days_to_lesson = 7 - (current_day_index - lesson_day_index)
                    lesson_date = now.date() + timedelta(days=days_to_lesson)

                # Создаём полное время занятия
                lesson_time = datetime.strptime(time_str, "%H:%M").time()
                lesson_datetime = datetime.combine(lesson_date, lesson_time).astimezone(local_tz)

                # Временные метки для напоминаний
                reminder_1h_before = lesson_datetime - timedelta(hours=1)
                reminder_24h_before = lesson_datetime - timedelta(days=1)
                reminder_5m_window_end = reminder_1h_before + timedelta(minutes=5)  # 5 минут после reminder_1h_before

                # Уникальные ключи для напоминаний
                reminder_key_1h = (user_name, lesson_datetime.isoformat(), "1 час")
                reminder_key_24h = (user_name, lesson_datetime.isoformat(), "24 часа")

                if reminder_1h_before <= now <= reminder_5m_window_end and reminder_key_1h not in sent_reminders:
                    print("[DEBUG] Условие за 1 час сработало")
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=f"Напоминание: у вас занятие через 1 час.\n{day} {time_str} - {description or 'Без описания'}"
                    )
                    sent_reminders.add(reminder_key_1h)

                elif reminder_24h_before <= now < reminder_1h_before and reminder_key_24h not in sent_reminders:
                    print("[DEBUG] Условие за 24 часа сработало")
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=f"Напоминание: у вас занятие через 24 часа.\n{day} {time_str} - {description or 'Без описания'}"
                    )
                    sent_reminders.add(reminder_key_24h)
            except Exception as e:
                print(f"[ERROR] Ошибка обработки занятия для {user_name}: {lesson}. Ошибка: {e}")

    print(f"[DEBUG] Напоминания отправлены: {sent_reminders}")
    print(
        f"[DEBUG] Напоминание для: {user_name}, занятие: {lesson}, ключ 1ч: {reminder_key_1h}, ключ 24ч: {reminder_key_24h}")
    print(f"[DEBUG] now: {now}, reminder_1h_before: {reminder_1h_before}, reminder_24h_before: {reminder_24h_before}")
    print(f"[DEBUG] Уникальные напоминания в sent_reminders: {sent_reminders}")
    sent_reminders.add(reminder_key_1h)
    print(f"[DEBUG] Добавлено напоминание за 1 час: {reminder_key_1h}")

# --- Функции загрузки расписания ---
def load_default_schedule():
    """Загружает расписание с GitHub."""
    try:
        github_raw_url = GITHUB_RAW_URL.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        response = requests.get(github_raw_url)
        response.raise_for_status()
        schedule = response.json()

        # Проверяем, соответствует ли формат
        for user, lessons in schedule.items():
            for lesson in lessons:
                if not all(key in lesson for key in ['day', 'time']):
                    raise ValueError(f"Ошибка в формате расписания: {lesson}")

        print(f"Расписание успешно загружено: {schedule}")  # Отладочный вывод
        return schedule
    except requests.RequestException as e:
        print(f"Ошибка загрузки расписания с GitHub: {e}")
        return {}
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Ошибка: Файл расписания содержит некорректные данные. {e}")
        return {}

def reset_schedule():
    """Сбрасывает расписание к стандартному."""
    global temporary_schedule
    temporary_schedule = load_default_schedule()
    print("Текущее расписание после сброса:", temporary_schedule)  # Отладочный вывод

    # Очищаем старые напоминания
    clean_sent_reminders()

def clean_sent_reminders():
    """Очищает устаревшие напоминания."""
    global sent_reminders
    now = datetime.now(local_tz)  # Текущее время в московской зоне

    # Лог до очистки
    print(f"[DEBUG] Очистка напоминаний. Текущее время: {now}")
    print(f"[DEBUG] Напоминания перед очисткой: {sent_reminders}")

    # Удаляем напоминания, у которых время урока прошло
    sent_reminders = {key for key in sent_reminders if datetime.fromisoformat(key[1]) > now}

    # Лог после очистки
    print(f"[DEBUG] Напоминания после очистки: {sent_reminders}")

# --- Функции обработки команд ---
async def start(update: Update, context: CallbackContext):
    """Обработка команды /start."""
    user_id = update.effective_chat.id
    user_name = update.effective_chat.username

    if not user_name:
        await update.message.reply_text(
            "У вас не установлен username в Telegram. Пожалуйста, добавьте username в настройках Telegram и повторите попытку."
        )
        return

    # Добавляем администратора в user_data
    if user_id == ADMIN_ID:
        user_data[user_name] = user_id
        print(f"[DEBUG] Администратор добавлен в user_data: {user_name} -> {user_id}")
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
    user_data[user_name] = user_id
    print(f"[DEBUG] User {user_name} добавлен в user_data: {user_name} -> {user_id}")

    # Немедленно обновляем user_data
    await update_user_data()

    await update.message.reply_text(
        "Добро пожаловать! Ваше расписание готово. Выберите действие:",
        reply_markup=get_main_menu(is_admin=False)
    )

async def update_user_data():
    """Обновляет список зарегистрированных пользователей."""
    global user_data
    # Здесь вы можете реализовать дополнительную логику проверки пользователей, если потребуется.
    print("[DEBUG] user_data обновлено:", user_data)

async def view_schedule(update: Update, context: CallbackContext):
    """Показывает расписание для конкретного ученика."""
    user_name = update.effective_chat.username  # Используем username
    user_schedule = temporary_schedule.get(user_name)

    if user_schedule:
        # Генерируем текст расписания из нового формата
        message = "\n".join([
            f"{lesson['day']} {lesson['time']} - {lesson['description']}"
            if lesson.get('description') else f"{lesson['day']} {lesson['time']}"
            for lesson in user_schedule
        ])
        await update.message.reply_text(f"Ваше расписание:\n{message}")
    else:
        await update.message.reply_text("У вас нет расписания. Пожалуйста, свяжитесь с администратором.")

async def view_students(update: Update, context: CallbackContext):
    """Показывает список всех зарегистрированных пользователей (только для администратора)."""
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    print(f"[DEBUG] user_data перед выводом учеников: {user_data}")

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

    try:
        # Перебираем всех пользователей и их расписания
        message = "\n\n".join([
            f"{user}:\n" + "\n".join(
                [f"{lesson['day']} {lesson['time']} - {lesson['description']}" for lesson in lessons]
            )
            for user, lessons in temporary_schedule.items()
        ])
        await update.message.reply_text(f"Все расписание:\n\n{message}")
    except Exception as e:
        print(f"[ERROR] Ошибка формирования расписания: {e}")
        await update.message.reply_text("Произошла ошибка при отображении расписания.")

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
        day = context.args[1]  # День недели
        time = context.args[2]  # Время
        description = " ".join(context.args[3:])  # Описание (если есть)

        new_lesson = {"day": day, "time": time, "description": description}

        if user_id in temporary_schedule:
            temporary_schedule[user_id].append(new_lesson)
        else:
            temporary_schedule[user_id] = [new_lesson]

        await update.message.reply_text(f"Расписание для {user_id} обновлено:\n{day} {time} - {description}")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование команды:\n/add_schedule user_id день время описание")

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
    scheduler = AsyncIOScheduler(event_loop=asyncio.get_event_loop())  # Используем текущий event loop

    # Задача: отправлять напоминания
    scheduler.add_job(
        send_reminders,  # Вызываем напрямую (без lambda)
        trigger="interval",
        minutes=10,
        args=[application],  # Передаём приложение в аргументах
        id="send_reminders"
    )

    # Задача: сбрасывать расписание каждую субботу в 23:00
    scheduler.add_job(
        reset_schedule,
        CronTrigger(day_of_week="sat", hour=23, minute=0),
        id="reset_schedule"
    )

    # Задача: обновлять список зарегистрированных пользователей каждые 5 минут
    scheduler.add_job(
        update_user_data,  # Вызываем напрямую
        trigger="interval",
        minutes=5,
        id="update_user_data"
    )
    scheduler.add_job(
        clean_sent_reminders,
        CronTrigger(hour=0, minute=0),  # Каждый день в 00:00
        id="clean_sent_reminders"
    )
    scheduler.start()
    print("Планировщик задач запущен.")

async def test_send_message(application):
    """Тест отправки сообщения админу."""
    try:
        await application.bot.send_message(chat_id=ADMIN_ID, text="Тестовое сообщение!")
        print("[DEBUG] Тестовое сообщение отправлено успешно.")
    except Exception as e:
        print(f"[ERROR] Ошибка отправки тестового сообщения: {e}")
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
    asyncio.run(main())

