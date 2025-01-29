import os
import json
import requests
from datetime import datetime, timedelta,timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters
import pytz
import logging
import asyncio
from telegram.error import NetworkError, RetryAfter, TimedOut
from asyncio import Semaphore
# Загрузка переменных окружения
load_dotenv()
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)
# --- Переменные окружения ---
BOT_TOKEN= os.getenv("BOT_TOKEN")
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
server_time = datetime.now(timezone.utc)  # Явно указываем UTC
print(f"Серверное время (UTC): {server_time}")
# Московское время
moscow_tz = pytz.timezone('Europe/Moscow')
moscow_time = datetime.now(moscow_tz)
print(f"Московское время: {moscow_time}")
# Устанавливаем временную зону для Москвы
local_tz = pytz.timezone('Europe/Moscow')
# Получаем текущее время в московской временной зоне
now = datetime.now(pytz.timezone('Europe/Moscow'))  # Устанавливаем МСК
print(f"Текущее московское время: {now}")

async def safe_send_message(bot, chat_id, text):
    """Безопасная отправка сообщения с обработкой ошибок."""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except RetryAfter as e:
        print(f"[WARNING] Превышен лимит запросов. Повтор через {e.retry_after} секунд.")
        await asyncio.sleep(e.retry_after)
        await safe_send_message(bot, chat_id, text)
    except (NetworkError, TimedOut) as e:
        print(f"[ERROR] Ошибка сети: {e}. Повтор через 5 секунд.")
        await asyncio.sleep(5)  # Ожидание перед повтором
        await safe_send_message(bot, chat_id, text)
    except Exception as e:
        print(f"[ERROR] Непредвиденная ошибка при отправке сообщения: {e}")

async def get_my_id(update: Update, context: CallbackContext):
    """Возвращает chat_id пользователя."""
    await update.message.reply_text(f"ADMIN_ID: {update.effective_chat.id}")

sent_reminders_24h = set()
sent_reminders_1h = set()

def calculate_lesson_date(day, time_str, now):
    """
    Рассчитывает ближайшую дату и время занятия.
    Args:
        day (str): День недели занятия (например, "Понедельник").
        time_str (str): Время занятия в формате "HH:MM".
        now (datetime): Текущее время.
    Returns:
        datetime: Дата и время ближайшего занятия.
    """
    list_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    # Индексы текущего дня недели и дня занятия
    current_day_index = now.weekday()  # 0 - Понедельник, 6 - Воскресенье
    lesson_day_index = list_days.index(day)  # Индекс дня занятия

    # Определяем, через сколько дней будет занятие
    if lesson_day_index == current_day_index:
        # Если занятие сегодня, проверяем, прошло ли время занятия
        lesson_time = datetime.strptime(time_str, "%H:%M").time()
        if now.time() > lesson_time:
            days_to_lesson = 7  # Переносим занятие на следующую неделю
        else:
            days_to_lesson = 0  # Занятие еще не началось
    elif lesson_day_index > current_day_index:
        # Занятие позже на этой неделе
        days_to_lesson = lesson_day_index - current_day_index
    else:
        # Занятие на следующей неделе
        days_to_lesson = 7 - (current_day_index - lesson_day_index)

    # Рассчитываем дату занятия
    lesson_date = now.date() + timedelta(days=days_to_lesson)

    # Объединяем дату и время
    lesson_time = datetime.strptime(time_str, "%H:%M").time()
    lesson_datetime = datetime.combine(lesson_date, lesson_time)

    return lesson_datetime

async def send_reminders_1h(application):
    """Отправляет напоминания за 1 час до занятий."""
    now = datetime.now(pytz.timezone('Europe/Moscow'))  # Текущее московское время
    global sent_reminders

    print(f"[DEBUG] send_reminders_1h запущен в {now}")

    for user_name, lessons in temporary_schedule.items():
        if user_name not in user_data:
            print(f"[DEBUG] Пользователь {user_name} не зарегистрирован. Пропускаем.")
            continue

        chat_id = user_data[user_name]

        for lesson in lessons:
            try:
                day = lesson['day']
                time_str = lesson['time']
                description = lesson.get('description', '')

                # Рассчитываем время занятия
                lesson_date = calculate_lesson_date(day, time_str, now)
                lesson_datetime = lesson_date.astimezone(local_tz)
                reminder_1h_before = lesson_datetime - timedelta(hours=1)
                reminder_5m_window_end = reminder_1h_before + timedelta(minutes=15)
                reminder_key_1h = (user_name, lesson_datetime.isoformat(), "1 час")

                # Проверяем условие для отправки напоминания
                if reminder_1h_before <= now <= reminder_5m_window_end and reminder_key_1h not in sent_reminders_1h:
                    # Отправляем сообщение
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=f"⏰ Напоминание: у вас занятие через 1 час!\n\n"
                             f"📅 {day}, {time_str} по МСК\n"
                             f"Описание: {description or 'Без описания'}\n\n"
                             "Удачи на занятии! 😊"
                    )
                    sent_reminders_1h.add(reminder_key_1h)
                    print(f"[DEBUG] Напоминание за 1 час отправлено: {reminder_key_1h}")

            except Exception as e:
                print(f"[ERROR] Ошибка обработки занятия: {lesson}. Ошибка: {e}")
                print(
                    f"[DEBUG] lesson_datetime: {lesson_datetime}, reminder_1h_before: {reminder_1h_before}, now: {now}")
                print(f"[DEBUG] reminder_5m_window_end: {reminder_5m_window_end}")

async def send_reminders_24h(application):
    """Отправляет напоминания за 24 часа до занятий."""
    now = datetime.now(pytz.timezone('Europe/Moscow'))  # Текущее московское время
    global sent_reminders

    print(f"[DEBUG] send_reminders_24h запущен в {now}")

    for user_name, lessons in temporary_schedule.items():
        if user_name not in user_data:
            print(f"[DEBUG] Пользователь {user_name} не зарегистрирован. Пропускаем.")
            continue

        chat_id = user_data[user_name]

        for lesson in lessons:
            try:
                day = lesson['day']
                time_str = lesson['time']
                description = lesson.get('description', '')

                # Рассчитываем время занятия
                lesson_date = calculate_lesson_date(day, time_str, now)
                lesson_datetime = lesson_date.astimezone(local_tz)

                # Рассчитываем время для напоминания за 24 часа
                reminder_24h_before = lesson_datetime - timedelta(days=1)

                # Создаём уникальный ключ для напоминания
                reminder_key_24h = (user_name, lesson_datetime.isoformat(), "24 часа")

                # Проверяем условие для отправки напоминания
                # now должно быть в пределах 15 минут от reminder_24h_before
                reminder_window_start = reminder_24h_before
                reminder_window_end = reminder_24h_before + timedelta(minutes=15)

                print(f"[DEBUG] reminder_24h_before: {reminder_24h_before}, "
                      f"reminder_window_start: {reminder_window_start}, "
                      f"reminder_window_end: {reminder_window_end}")

                if reminder_window_start <= now <= reminder_window_end and reminder_key_24h not in sent_reminders_24h:
                    # Отправляем сообщение
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔔 Напоминание: у вас занятие через 24 часа.\n\n"
                             f"📅 {day}, {time_str} по МСК\n"
                             f"Описание: {description or 'Без описания'}\n\n"
                             "Подготовьтесь заранее! 👍"
                    )
                    sent_reminders_24h.add(reminder_key_24h)
                    print(f"[DEBUG] Напоминание за 24 часа отправлено: {reminder_key_24h}")

            except Exception as e:
                print(f"[ERROR] Ошибка обработки занятия: {lesson}. Ошибка: {e}")
                print(f"[DEBUG] lesson_datetime: {lesson_datetime}, now: {now}")

    print(f"[DEBUG] Напоминания за 24 часа отправлены: {sent_reminders_24h}")

async def send_reminders(application):
    """Главная функция для отправки напоминаний."""
    await update_user_data()  # Обновляем список зарегистрированных пользователей перед отправкой напоминаний
    clean_sent_reminders()  # Очищаем старые напоминания

    now = datetime.now(local_tz)  # Текущее время в московской зоне

    # Отправляем напоминания
    await send_reminders_24h(application, now)
    await send_reminders_1h(application, now)

    # Финальный отладочный вывод
    print(f"[DEBUG] Уникальные напоминания в sent_reminders: {sent_reminders}")
# --- Функции загрузки расписания ---
last_valid_schedule = {}

def load_default_schedule():
    """Загружает расписание с GitHub."""
    global last_valid_schedule
    try:
        # Формируем корректный URL
        github_raw_url = GITHUB_RAW_URL.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        response = requests.get(github_raw_url, timeout=10)
        response.raise_for_status()  # Проверяем успешность запроса

        # Парсим JSON-данные
        schedule = response.json()
        print("[DEBUG] Загруженное расписание:", schedule)  # Отладочный вывод

        # Проверяем структуру расписания
        valid_schedule = {}
        for user, data in schedule.items():
            if not isinstance(data, dict) or 'schedule' not in data:
                print(f"[WARNING] Некорректные данные для пользователя {user}. Пропускаем.")
                continue

            if not isinstance(data['schedule'], list):
                print(f"[WARNING] Расписание для пользователя {user} некорректное. Пропускаем.")
                continue

            # Проверяем каждый элемент расписания
            valid_lessons = []
            for lesson in data['schedule']:
                if not isinstance(lesson, dict) or 'day' not in lesson or 'time' not in lesson:
                    print(f"[WARNING] Некорректный урок для пользователя {user}: {lesson}. Пропускаем.")
                    continue
                valid_lessons.append(lesson)

            if valid_lessons:
                valid_schedule[user] = {"name": data.get("name", "Без имени"), "schedule": valid_lessons}
            else:
                print(f"[WARNING] У пользователя {user} нет валидных уроков. Пропускаем.")

        # Сохраняем последнее валидное расписание
        if valid_schedule:
            last_valid_schedule = valid_schedule
            print("[DEBUG] Последнее валидное расписание сохранено.")
        else:
            print("[WARNING] Все данные расписания некорректны. Используем предыдущее валидное расписание.")

        return valid_schedule

    except requests.RequestException as e:
        print(f"[ERROR] Ошибка загрузки расписания с GitHub: {e}")
    except json.JSONDecodeError as e:
        print(f"[ERROR] Ошибка парсинга JSON: {e}")
    except Exception as e:
        print(f"[ERROR] Неизвестная ошибка: {e}")

    # Возвращаем последнее валидное расписание в случае ошибки
    if last_valid_schedule:
        print("[WARNING] Используется последнее валидное расписание.")
        return last_valid_schedule

    # Если ничего не получилось загрузить
    print("[ERROR] Нет доступного расписания. Возвращаем пустой словарь.")
    return {}

def reset_schedule():
    """Сбрасывает расписание к стандартному."""
    global temporary_schedule
    try:
        # Загружаем новое расписание с проверкой формата
        new_schedule = load_default_schedule()
        if not new_schedule or not isinstance(new_schedule, dict):  # Если расписание пустое или неверного формата
            raise ValueError("Загружено пустое или некорректное расписание!")

        # Проверяем корректность каждого пользователя и его расписания
        validated_schedule = {}
        for user, data in new_schedule.items():
            if not isinstance(data, dict) or not isinstance(data.get('schedule'), list):
                print(f"[WARNING] Расписание для пользователя {user} некорректное. Пропускаем.")
                continue
            # Добавляем валидированные данные в новое расписание
            validated_schedule[user] = data

        if not validated_schedule:  # Если после проверки нет валидных данных
            raise ValueError("После проверки расписание оказалось пустым!")

        # Присваиваем временной переменной проверенное расписание
        temporary_schedule = validated_schedule
        print("[DEBUG] Текущее расписание после сброса:", temporary_schedule)

    except Exception as e:
        print(f"[ERROR] Ошибка при сбросе расписания: {e}")

    # Очищаем старые напоминания
    clean_sent_reminders()

def clean_sent_reminders():
    global sent_reminders_24h, sent_reminders_1h
    now = datetime.now(pytz.timezone('Europe/Moscow'))

    # Очистка напоминаний за 24 часа
    sent_reminders_24h = {
        key for key in sent_reminders_24h
        if datetime.fromisoformat(key[1]).astimezone(pytz.timezone('Europe/Moscow')) > now
    }

    # Очистка напоминаний за 1 час
    sent_reminders_1h = {
        key for key in sent_reminders_1h
        if datetime.fromisoformat(key[1]).astimezone(pytz.timezone('Europe/Moscow')) > now
    }

    # Отладочный вывод
    print(f"[DEBUG] Устаревшие напоминания очищены.")
    print(f"[DEBUG] Напоминания за 24 часа после очистки: {len(sent_reminders_24h)}")
    print(f"[DEBUG] Напоминания за 1 час после очистки: {len(sent_reminders_1h)}")
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
        "Добро пожаловать в бота расписания! 👋\n"
        "Ваше расписание уже готово. Используйте меню ниже, чтобы узнать больше. 👇",
        reply_markup=get_main_menu(is_admin=False)
    )

async def update_user_data():
    """Обновляет список зарегистрированных пользователей."""
    global user_data
    global temporary_schedule

    print("[DEBUG] Обновление user_data началось...")

    # Проверяем данные расписания и удаляем некорректные
    for user, data in list(temporary_schedule.items()):
        if not isinstance(data, list):  # Если расписание не список
            print(f"[WARNING] Некорректные данные для пользователя {user}. Удаляем.")
            del temporary_schedule[user]
            continue

        # Оставляем только корректные занятия
        temporary_schedule[user] = [
            lesson for lesson in data if isinstance(lesson, dict) and 'day' in lesson and 'time' in lesson
        ]

    # Добавляем новых пользователей из расписания
    for user_name in temporary_schedule.keys():
        if user_name not in user_data:
            user_data[user_name] = None  # Пока пользователь не зарегистрировался через /start
            print(f"[DEBUG] Добавлен новый пользователь из расписания: {user_name}")

    # Удаляем пользователей, которых нет в расписании
    for user_name in list(user_data.keys()):
        if user_name not in temporary_schedule:
            print(f"[DEBUG] Пользователь {user_name} удалён из user_data (нет в расписании).")
            del user_data[user_name]

    print("[DEBUG] user_data обновлено:", user_data)

async def view_schedule(update: Update, context: CallbackContext):
    """Показывает расписание для конкретного ученика."""
    user_name = update.effective_chat.username
    user_data = temporary_schedule.get(user_name)

    # Проверяем, есть ли данные для пользователя
    if not user_data or not isinstance(user_data, dict) or 'schedule' not in user_data:
        await update.message.reply_text("У вас нет расписания. Пожалуйста, свяжитесь с администратором.")
        return

    user_schedule = user_data.get("schedule")

    # Проверяем, является ли расписание списком
    if not isinstance(user_schedule, list):
        print(f"[WARNING] Некорректное расписание для пользователя {user_name}.")
        await update.message.reply_text("Ваше расписание содержит ошибку. Свяжитесь с администратором.")
        return

    # Формируем текст расписания
    message = "\n".join([
        f"{lesson['day']} {lesson['time']} - {lesson.get('description', '')}"
        for lesson in user_schedule if isinstance(lesson, dict)  # Убедимся, что урок — словарь
    ])

    if not message:  # Если после обработки нет корректных уроков
        await update.message.reply_text("Ваше расписание отсутствует или некорректно.")
        return

    # Отправляем расписание
    user_full_name = user_data.get("name", "Неизвестный пользователь")
    await update.message.reply_text(f"Ваше расписание, {user_full_name}:\n{message}")

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
        message = []
        for user, data in temporary_schedule.items():
            # Проверяем корректность данных пользователя
            if not isinstance(data, dict) or 'schedule' not in data or 'name' not in data:
                print(f"[WARNING] Некорректные данные для пользователя {user}. Пропускаем.")
                continue

            # Извлекаем расписание и имя пользователя
            user_name = data.get('name', user)
            user_schedule = data.get('schedule', [])

            # Проверяем, что расписание — список
            if not isinstance(user_schedule, list):
                print(f"[WARNING] Расписание для пользователя {user_name} некорректное. Пропускаем.")
                continue

            # Формируем текст расписания для текущего пользователя
            user_schedule_text = "\n".join([
                f"{lesson['day']} {lesson['time']} - {lesson.get('description', '')}"
                for lesson in user_schedule if isinstance(lesson, dict)
            ])

            if user_schedule_text:  # Добавляем только если есть корректные уроки
                message.append(f"{user_name}:\n{user_schedule_text}")

        # Проверяем, есть ли что отправить
        if not message:
            await update.message.reply_text("Расписание отсутствует или некорректно.")
            return

        # Отправляем все расписания
        await update.message.reply_text("\n\n".join(message))

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
    buttons = [[KeyboardButton("Старт")]]  # Кнопка "Старт" будет доступна всем

    if is_admin:
        # Кнопки для администратора
        buttons.extend([
            [KeyboardButton("Просмотреть всё расписание")],
            [KeyboardButton("Редактировать расписание"), KeyboardButton("Сбросить расписание")],
            [KeyboardButton("Ученики")]
        ])
    else:
        # Кнопки для ученика
        buttons.append([KeyboardButton("Моё расписание")])

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
# --- Обработчик кнопок ---
async def button_handler(update: Update, context: CallbackContext):
    """Обрабатывает действия при нажатии кнопок."""
    user_id = update.effective_chat.id
    text = update.message.text

    if text == "Моё расписание":
        await view_schedule(update, context)
    elif text == "Старт":
        await start(update, context)
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
    """
    Настраивает планировщик задач.
    """
    try:
        # Используем безопасный метод для работы с event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        print(f"[DEBUG] Текущий event_loop: {loop}")
    except RuntimeError as e:
        print(f"[ERROR] Ошибка с event_loop: {e}")
        return  # Выходим, если не удалось получить или создать event loop

    # Инициализируем планировщик
    scheduler = AsyncIOScheduler(event_loop=loop)

    # Добавляем задачи
    try:
        # Задача: отправлять напоминания за 24 часа
        scheduler.add_job(
            send_reminders_24h,
            trigger="interval",
            minutes=15,  # Интервал выполнения задачи
            args=[application],
            id="send_reminders_24h"
        )
        print("[DEBUG] Задача send_reminders_24h успешно добавлена.")

        # Задача: отправлять напоминания за 1 час
        scheduler.add_job(
            send_reminders_1h,
            trigger="interval",
            minutes=5,  # Интервал выполнения задачи
            args=[application],
            id="send_reminders_1h"
        )
        print("[DEBUG] Задача send_reminders_1h успешно добавлена.")

        # Задача: сбрасывать расписание каждую субботу в 23:00
        scheduler.add_job(
            reset_schedule,
            CronTrigger(day_of_week="sun", hour=23, minute=0),
            id="reset_schedule"
        )
        print("[DEBUG] Задача reset_schedule успешно добавлена.")

        # Задача: обновлять список зарегистрированных пользователей каждые 5 минут
        scheduler.add_job(
            update_user_data,
            trigger="interval",
            minutes=5,
            id="update_user_data"
        )
        print("[DEBUG] Задача update_user_data успешно добавлена.")

        # Задача: очищать старые напоминания каждый день в 00:00
        scheduler.add_job(
            clean_sent_reminders,
            CronTrigger(hour=0, minute=0),
            id="clean_sent_reminders"
        )
        print("[DEBUG] Задача clean_sent_reminders успешно добавлена.")
    except Exception as e:
        print(f"[ERROR] Ошибка при добавлении задач в планировщик: {e}")

    # Запускаем планировщик
    try:
        scheduler.start()
        print("Планировщик задач запущен.")
    except Exception as e:
        print(f"[ERROR] Ошибка при запуске планировщика: {e}")

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
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[ERROR] Ошибка при запуске бота: {e}")


