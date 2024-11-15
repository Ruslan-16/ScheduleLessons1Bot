import os
import re
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, ChatMemberHandler
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Загружаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DB_PATH = "schedule.db"  # Путь к базе данных SQLite


# Кастомный HTTP-сервер для возврата HTTP 200 OK на все запросы
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def run_http_server():
    server = HTTPServer(('0.0.0.0', 5000), HealthCheckHandler)
    server.serve_forever()


# Запуск HTTP-сервера в фоновом потоке
threading.Thread(target=run_http_server, daemon=True).start()


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


# Создаем клавиатуру для администратора
def get_admin_keyboard():
    keyboard = [
        ["/schedule", "/remove_schedule"],
        ["/users", "/my_schedule"],
        ["/all_schedules"]  # Новая команда для просмотра расписания всех пользователей
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# Команда /start для регистрации пользователя
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                       (user.id, user.username, user.first_name))
        conn.commit()

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Доступные команды:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await update.message.reply_text("Вы зарегистрированы! Вы будете получать напоминания о занятиях.")


# Команда /schedule для добавления расписания (только администратор)
async def schedule(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для изменения расписания.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /schedule @username1 день1 время1 описание1; @username2 день2 время2 описание2; ..."
        )
        return

    schedule_text = " ".join(context.args)
    entries = schedule_text.split(";")
    added_entries = []

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        for entry in entries:
            match = re.match(r"@(\S+)\s+(\S+)\s+(\S+)\s+(.+)", entry.strip())
            if match:
                username, day, time, description = match.groups()
                cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
                result = cursor.fetchone()

                if result:
                    user_id = result[0]
                    cursor.execute('''
                        INSERT INTO schedule (user_id, day, time, description, reminder_sent)
                        VALUES (?, ?, ?, ?, 0)
                    ''', (user_id, day, time, description))
                    added_entries.append(f"@{username} {day} {time} - {description}")
                else:
                    await update.message.reply_text(f"Пользователь @{username} не найден.")

        conn.commit()

    if added_entries:
        confirmation = "Занятия добавлены в расписание:\n" + "\n".join(added_entries)
        await update.message.reply_text(confirmation)
    else:
        await update.message.reply_text(
            "Ошибка в формате команды или указаны неверные username'ы. Пожалуйста, проверьте правильность ввода."
        )


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


# Команда /my_schedule для просмотра расписания
async def my_schedule(update: Update, context: CallbackContext):
    user = update.effective_user
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT day, time, description FROM schedule WHERE user_id = ?', (user.id,))
        schedule = cursor.fetchall()

    if not schedule:
        await update.message.reply_text("Ваше расписание пусто.")
        return

    text = "Ваше расписание:\n\n"
    for day, time, description in schedule:
        text += f"{day} {time} - {description}\n"
    await update.message.reply_text(text)


# Команда /all_schedules для просмотра расписаний всех пользователей (только администратор)
async def all_schedules(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав для просмотра расписания всех пользователей.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.first_name, u.username, s.day, s.time, s.description
            FROM schedule s
            JOIN users u ON s.user_id = u.user_id
            ORDER BY s.day, s.time
        ''')
        schedules = cursor.fetchall()

    if not schedules:
        await update.message.reply_text("Расписание всех пользователей пусто.")
        return

    text = "Расписание всех пользователей:\n\n"
    for first_name, username, day, time, description in schedules:
        text += f"{first_name} (@{username}) - {day} {time}: {description}\n"
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


# Обработчик удаления пользователя при выходе из чата с ботом
async def handle_chat_member_update(update: Update, context: CallbackContext):
    if update.my_chat_member.new_chat_member.status == 'kicked':
        user_id = update.effective_user.id
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM schedule WHERE user_id = ?', (user_id,))
            conn.commit()
        print(f"Пользователь {user_id} удален из базы данных после удаления бота.")


# Функция для отправки напоминаний
async def send_reminders(application: Application):
    now = datetime.now()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, user_id, day, time, description, reminder_sent FROM schedule')
        schedule = cursor.fetchall()

    for record in schedule:
        lesson_id, user_id, day, time, description, reminder_sent = record

        try:
            day_of_week = datetime.strptime(day, "%A").weekday()
            lesson_time = datetime.strptime(time, "%H:%M").time()
            lesson_datetime = datetime.combine(now, lesson_time)
            days_diff = (day_of_week - now.weekday()) % 7
            lesson_datetime = lesson_datetime + timedelta(days=days_diff)
            reminder_time = lesson_datetime - timedelta(hours=1)

            if reminder_sent == 0 and reminder_time <= now < lesson_datetime:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: {description} начнется через 1 час, в {lesson_datetime.strftime('%H:%M')}!"
                )
                cursor.execute('UPDATE schedule SET reminder_sent = 1 WHERE id = ?', (lesson_id,))
                conn.commit()

            if now.weekday() == 5 and now.hour == 23 and now.minute == 59:
                cursor.execute('UPDATE schedule SET reminder_sent = 0')
                conn.commit()

        except Exception as e:
            print(f"Ошибка при отправке напоминания: {e}")


# Основная функция для запуска бота
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("schedule", schedule))
    application.add_handler(CommandHandler("remove_schedule", remove_schedule))
    application.add_handler(CommandHandler("my_schedule", my_schedule))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("all_schedules", all_schedules))  # Регистрация новой команды

    # Регистрация обработчика для удаления пользователя
    application.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))

    # Запуск задачи для отправки напоминаний каждую минуту
    application.job_queue.run_repeating(send_reminders, interval=60, first=10)

    # Запуск бота в режиме Polling
    application.run_polling()


if __name__ == "__main__":
    main()
