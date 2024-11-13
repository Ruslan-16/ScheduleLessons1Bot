import sqlite3
from datetime import datetime, timedelta
from telegram import Bot

# Токен вашего бота от BotFather
BOT_TOKEN = "7913714398:AAGQgwxx5WpMlO7xyiVmUzJZan5yxew8b3Q"
# Путь к базе данных
DB_PATH = "schedule.db"

# Создание бота
bot = Bot(token=BOT_TOKEN)


# Функция для отправки напоминаний
def send_reminder():
    now = datetime.now()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, day, time, description FROM schedule')
        schedule = cursor.fetchall()

    for user_id, day, time, description in schedule:
        # Парсим день и время занятия
        try:
            day_of_week = datetime.strptime(day, "%A").weekday()  # Понедельник = 0, Воскресенье = 6
            lesson_time = datetime.strptime(time, "%H:%M").time()
            lesson_datetime = datetime.combine(now, lesson_time)  # Комбинируем с текущей датой
            days_diff = (day_of_week - now.weekday()) % 7  # Расстояние между текущим днем и днем занятия
            lesson_datetime = lesson_datetime + timedelta(days=days_diff)
        except ValueError as e:
            print(f"Ошибка при парсинге данных: {e}")
            continue

        # Напоминаем за 1 час до занятия
        reminder_time = lesson_datetime - timedelta(hours=1)

        # Если время напоминания в будущем
        if reminder_time > now:
            # Отправляем напоминание за 1 час
            bot.send_message(
                chat_id=user_id,
                text=f"Напоминание: ваше занятие по {description} начнется через 1 час, в "
                     f"{lesson_datetime.strftime('%H:%M')}!"
            )


if __name__ == "__main__":
    send_reminder()
