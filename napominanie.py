import os
import re
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackContext, ChatMemberHandler

# Загружаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DB_PATH = "schedule.db"  # Путь к базе данных SQLite


# Инициализация базы данных
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                day TEXT,
                time TEXT,
                description TEXT,
                reminder_sent BOOLEAN DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        conn.commit()


# Клавиатура для администратора (с двумя рядами кнопок)
def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("/schedule"), KeyboardButton("/remove_schedule")],
        [KeyboardButton("/users"), KeyboardButton("/my_schedule")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# Клавиатура для ученика (с одной кнопкой)
def get_user_keyboard():
    keyboard = [
        [KeyboardButton("/my_schedule")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# Команда /start для регистрации пользователя и показа клавиатуры
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                       (user.id, user.username, user.first_name))
        conn.commit()

    # Показ клавиатуры в зависимости от роли
    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Доступные команды:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=get_user_keyboard()
        )


# Команда /my_schedule для просмотра расписания
async def my_schedule(update: Update, context: CallbackContext):
    user = update.effective_user
    text = "Ваше расписание:\n\n"

    # Проверка, если администратор - показать расписание всех учеников
    if user.id == ADMIN_ID:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT users.first_name, schedule.day, schedule.time, schedule.description 
                FROM schedule 
                JOIN users ON schedule.user_id = users.user_id 
                ORDER BY schedule.day, schedule.time
            ''')
            schedule = cursor.fetchall()

        if not schedule:
            text = "Общее расписание пусто."
        else:
            for first_name, day, time, description in schedule:
                text += f"{first_name}: {day} {time} - {description}\n"
    else:
        # Для учеников показать только их расписание
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT day, time, description FROM schedule WHERE user_id = ?', (user.id,))
            schedule = cursor.fetchall()

        if not schedule:
            text = "Ваше расписание пусто."
        else:
            for day, time, description in schedule:
                text += f"{day} {time} - {description}\n"

    await update.message.reply_text(text)


# Команда /users для отображения списка пользователей (только администратор)
async def list_users(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для просмотра списка пользователей.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT username, first_name FROM users')
        users = cursor.fetchall()

    if not users:
        await update.message.reply_text("Нет зарегистрированных пользователей.")
        return

    text = "Зарегистрированные пользователи:\n"
    for username, first_name in users:
        text += f"{first_name} (@{username})\n"
    await update.message.reply_text(text)


# Команда /remove_schedule для удаления расписания (только администратор)
async def remove_schedule(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для удаления расписания.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Использование: /remove_schedule @username")
        return

    username = context.args[0].lstrip('@')

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()

        if result:
            user_id = result[0]
            cursor.execute('DELETE FROM schedule WHERE user_id = ?', (user_id,))
            conn.commit()
            await update.message.reply_text(f"Все занятия для @{username} были удалены из расписания.")
        else:
            await update.message.reply_text(f"Пользователь @{username} не найден.")


# Основная функция для запуска бота
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("my_schedule", my_schedule))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("remove_schedule", remove_schedule))

    # Запуск бота в режиме Polling
    application.run_polling()


if __name__ == "__main__":
    main()
