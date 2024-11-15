import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, ChatMemberHandler

# Настройки переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DB_PATH = "schedule.db"  # Путь к базе данных SQLite


# Функция для инициализации базы данных
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


# Клавиатура для администратора, показывающая команду /my_schedule
def get_admin_keyboard():
    keyboard = [[
        "/schedule", "/remove_schedule", "/users", "/my_schedule"
    ]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


# Клавиатура для учеников, показывающая только команду /my_schedule
def get_student_keyboard():
    keyboard = [["/my_schedule"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


# Команда /start для регистрации пользователя и отображения клавиатуры
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                       (user.id, user.username, user.first_name))
        conn.commit()

    # Проверяем, является ли пользователь администратором, чтобы показать нужную клавиатуру
    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Доступные команды:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=get_student_keyboard()
        )


# Команда /my_schedule для отображения расписания
async def my_schedule(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id == ADMIN_ID:
        # Если пользователь — администратор, выводим расписание всех учеников
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT users.first_name, users.username, schedule.day, schedule.time, schedule.description 
                FROM schedule 
                JOIN users ON schedule.user_id = users.user_id
                ORDER BY schedule.day, schedule.time
            ''')
            schedules = cursor.fetchall()

        if schedules:
            text = "Расписание всех учеников:\n\n"
            for first_name, username, day, time, description in schedules:
                text += f"{first_name} (@{username}): {day} {time} - {description}\n"
            await update.message.reply_text(text)
        else:
            await update.message.reply_text("Расписание пока пусто.")
    else:
        # Если пользователь — ученик, выводим его расписание
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT day, time, description FROM schedule WHERE user_id = ?', (user.id,))
            schedule = cursor.fetchall()

        if schedule:
            text = "Ваше расписание:\n\n"
            for day, time, description in schedule:
                text += f"{day} {time} - {description}\n"
            await update.message.reply_text(text)
        else:
            await update.message.reply_text("Ваше расписание пусто.")


# Остальные команды и обработчики (например, добавление, удаление расписания) остаются без изменений


# Основная функция для запуска бота
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("my_schedule", my_schedule))

    # Запуск бота в режиме Polling
    application.run_polling()


if __name__ == "__main__":
    main()
