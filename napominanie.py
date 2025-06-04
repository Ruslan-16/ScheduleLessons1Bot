import os
import json
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import pytz
import logging
import asyncio
from telegram.error import NetworkError, RetryAfter, TimedOut

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Ruslan-16/ScheduleLessons1Bot/main/users.json"

logging.basicConfig(level=logging.INFO)
logging.getLogger('apscheduler').setLevel(logging.DEBUG)

temporary_schedule = {}
user_data = {}
sent_reminders_24h = set()
sent_reminders_1h = set()
local_tz = pytz.timezone('Europe/Moscow')

def load_default_schedule():
    global temporary_schedule
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            temporary_schedule = {u: d for u, d in data.items() if 'schedule' in d}
    except Exception as e:
        print(f"[ERROR] Не удалось загрузить расписание: {e}")
        temporary_schedule = {}

def clean_sent_reminders():
    now = datetime.now(local_tz)
    global sent_reminders_24h, sent_reminders_1h

    def parse_with_tz(dt_str):
        dt = datetime.fromisoformat(dt_str)
        return dt if dt.tzinfo else local_tz.localize(dt)

    sent_reminders_24h = {
        k for k in sent_reminders_24h if parse_with_tz(k[1]) > now
    }
    sent_reminders_1h = {
        k for k in sent_reminders_1h if parse_with_tz(k[1]) > now
    }

async def safe_send(bot, chat_id, text):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await safe_send(bot, chat_id, text)
    except (NetworkError, TimedOut):
        await asyncio.sleep(5)
        await safe_send(bot, chat_id, text)
    except Exception as e:
        print(f"[ERROR] {e}")

async def update_user_data():
    global user_data
    for user in temporary_schedule:
        if user not in user_data:
            user_data[user] = None
    for user in list(user_data.keys()):
        if user not in temporary_schedule:
            del user_data[user]

async def send_reminders_24h(app):
    now = datetime.now(local_tz)
    for user_name, data in temporary_schedule.items():
        chat_id = user_data.get(user_name)
        if not chat_id:
            continue
        for lesson in data['schedule']:
            lesson_datetime = get_lesson_datetime(lesson['day'], lesson['time'])
            reminder_time = lesson_datetime - timedelta(days=1)
            key = (user_name, lesson_datetime.isoformat(), "24h")

            if reminder_time <= now <= reminder_time + timedelta(minutes=15) and key not in sent_reminders_24h:
                text = (
                    f"Hello! 😊 Напоминаем о Вашем предстоящем занятии в {lesson['day']} в {lesson['time']}.\n"
                    f"Если планы изменятся – пожалуйста, предупредите заранее. 😉\n\n"
                    f"⏰ Утренние занятия (до 12:00) – предупреждаем за день, иначе занятие сгорает.\n"
                    f"⏰ Изменения возможны до 20:00 накануне (для занятий до 12:00) или минимум за 4 часа (для занятий после 12:00)."
                )
                await safe_send(app.bot, chat_id, text)
                sent_reminders_24h.add(key)
                print(f"[DEBUG] Отправлено напоминание за 24 часа: {key}")

async def send_reminders_1h(app):
    now = datetime.now(local_tz)
    for user_name, data in temporary_schedule.items():
        chat_id = user_data.get(user_name)
        if not chat_id:
            continue
        for lesson in data['schedule']:
            lesson_datetime = get_lesson_datetime(lesson['day'], lesson['time'])
            reminder_time = lesson_datetime - timedelta(hours=1)
            key = (user_name, lesson_datetime.isoformat(), "1h")

            if reminder_time <= now <= reminder_time + timedelta(minutes=15) and key not in sent_reminders_1h:
                text = (
                    f"Hey there! 🕒 Напоминаем, что у Вас сегодня занятие по английскому в {lesson['time']}.\n"
                    f"⌛️ Если опаздываете на 5–10 минут, просто дайте знать."
                )
                await safe_send(app.bot, chat_id, text)
                sent_reminders_1h.add(key)
                print(f"[DEBUG] Отправлено напоминание за 1 час: {key}")


async def test_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для немедленной проверки напоминаний."""
    app = context.application
    await update_user_data()  # Обновляем данные
    await send_reminders_24h(app)  # Проверяем напоминания за 24 часа
    await send_reminders_1h(app)   # Проверяем напоминания за 1 час
    await update.message.reply_text("Тест напоминаний выполнен. Проверьте логи или Telegram!")

def get_lesson_datetime(day, time_str):
    now = datetime.now(local_tz)
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    day_idx = days.index(day)
    now_idx = now.weekday()
    days_ahead = (day_idx - now_idx) % 7
    lesson_date = now.date() + timedelta(days=days_ahead)
    lesson_time = datetime.strptime(time_str, "%H:%M").time()

    naive_dt = datetime.combine(lesson_date, lesson_time)
    lesson_datetime = local_tz.localize(naive_dt)

    return lesson_datetime


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_chat.username
    user_id = update.effective_chat.id
    welcome_text = (
        "Welcome! 😊👋\n"
        "Я — Ваш бот-помощник 🤖💬\n"
        "Буду напоминать вам о занятиях, чтобы вы ничего не пропустили 🧠✨\n\n"
        "🔔 Напоминания приходят за день до занятия и ещё раз — перед началом занятия ⏰📅\n"
        "А если вдруг захотите сами заглянуть в расписание — я всегда к вашим услугам! 📖"
    )

    if user_id == ADMIN_ID:
        user_data[user_name] = user_id
        await update.message.reply_text(welcome_text)
        await update.message.reply_text("Добро пожаловать, администратор!", reply_markup=menu(True))
    elif user_name in temporary_schedule:
        user_data[user_name] = user_id
        await update.message.reply_text(welcome_text)
        await update.message.reply_text("Добро пожаловать!", reply_markup=menu(False))
    else:
        await update.message.reply_text("Вы не в расписании.")


def menu(admin=False):
    buttons = [[KeyboardButton("Старт")]]
    if admin:
        buttons.append([KeyboardButton("Все расписания"), KeyboardButton("Ученики")])
        buttons.append([KeyboardButton("Редактировать расписание")])
    else:
        buttons.append([KeyboardButton("Моё расписание")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Старт":
        await start(update, context)
    elif text == "Моё расписание":
        await show_my_schedule(update)
    elif text == "Все расписания" and update.effective_chat.id == ADMIN_ID:
        await show_all(update)
    elif text == "Ученики" and update.effective_chat.id == ADMIN_ID:
        await show_users(update)
    elif text == "Редактировать расписание" and update.effective_chat.id == ADMIN_ID:
        await edit_schedule_prompt(update, context)
    else:
        await update.message.reply_text("Неизвестная команда.")

async def edit_schedule_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """Введите имя ученика и новое занятие в формате:

ИмяПользователя
{"day": "Понедельник", "time": "10:00", "description": "Тема"}

Пример:
RuslanAlmasovich
{"day": "Среда", "time": "13:00", "description": "Физика"}"""
    )

    return

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        return

    lines = update.message.text.strip().split("\n")
    if len(lines) != 2:
        await update.message.reply_text("Ошибка формата. Введите имя и JSON через новую строку.")
        return

    user_name, json_str = lines
    user_name = user_name.strip()

    try:
        new_lesson = json.loads(json_str)

        if user_name not in temporary_schedule:
            await update.message.reply_text("Пользователь не найден.")
            return

        temporary_schedule[user_name]["schedule"].append(new_lesson)

        # Сохраняем обновлённое расписание
        with open("users.json", "w", encoding="utf-8") as f:
            json.dump(temporary_schedule, f, ensure_ascii=False, indent=4)

        await update.message.reply_text(f"Новое занятие добавлено для {user_name}.")

    except json.JSONDecodeError:
        await update.message.reply_text("Ошибка: JSON некорректен.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def show_my_schedule(update: Update):
    user = update.effective_chat.username
    data = temporary_schedule.get(user)
    if not data:
        await update.message.reply_text("Нет расписания.")
        return
    text = "\n".join([f"{l['day']} {l['time']} - {l.get('description','')}" for l in data['schedule']])
    await update.message.reply_text(text)

async def show_all(update: Update):
    text = []
    for user, data in temporary_schedule.items():
        lessons = "\n".join([f"{l['day']} {l['time']} - {l.get('description','')}" for l in data['schedule']])
        text.append(f"{user}:\n{lessons}")
    await update.message.reply_text("\n\n".join(text))

async def show_users(update: Update):
    await update.message.reply_text("\n".join(user_data.keys()))

def schedule_jobs(app):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(update_user_data, "interval", minutes=5)
    scheduler.add_job(clean_sent_reminders, CronTrigger(hour=0))
    scheduler.add_job(send_reminders_24h, "interval", minutes=15, args=[app])
    scheduler.add_job(send_reminders_1h, "interval", minutes=5, args=[app])
    scheduler.start()

def main():
    load_default_schedule()
    app = Application.builder().token(BOT_TOKEN).build()
    schedule_jobs(app)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    app.add_handler(CommandHandler("test_reminders", test_reminders))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_input))
    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")

