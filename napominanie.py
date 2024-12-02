import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import shutil

LOG_DIR = "/persistent_data"
LOG_FILE_PATH = f"{LOG_DIR}/logs.txt"

# Проверка и создание директории и файла для логов
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    print(f"Директория логов создана или уже существует: {LOG_DIR}")

    if not os.path.exists(LOG_FILE_PATH):
        with open(LOG_FILE_PATH, 'w') as f:
            pass
        print(f"Файл логов создан: {LOG_FILE_PATH}")
    else:
        print(f"Файл логов уже существует: {LOG_FILE_PATH}")

    # Настройка логирования только после успешного создания файла
    logging.basicConfig(
        filename=LOG_FILE_PATH,
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    print("Логирование настроено.")
except Exception as e:
    print(f"Ошибка при настройке логирования: {e}")
    raise

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
JSON_DB_PATH = os.getenv("JSON_DB_PATH", "/persistent_data/users.json")
scheduler = AsyncIOScheduler()

if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
if ADMIN_ID == 0:
    raise ValueError("Переменная окружения ADMIN_ID не установлена или равна 0!")


# --- Вспомогательные функции ---
def init_json_db():
    """Создаёт файл базы данных, если его нет."""
    os.makedirs(os.path.dirname(JSON_DB_PATH), exist_ok=True)
    if not os.path.exists(JSON_DB_PATH):
        logging.info(f"Создаю файл базы данных {JSON_DB_PATH}...")
        with open(JSON_DB_PATH, 'w') as f:
            json.dump({"users": {}, "schedule": {}, "standard_schedule": {}}, f)
    else:
        logging.info(f"Файл базы данных {JSON_DB_PATH} уже существует.")

def backup_json_file():
    """Создаёт резервную копию файла данных."""
    backup_path = f"{JSON_DB_PATH}.backup"
    if os.path.exists(JSON_DB_PATH):
        shutil.copy(JSON_DB_PATH, backup_path)
        logging.info(f"Резервная копия создана: {backup_path}")


def load_data():
    """Загружает данные из JSON-файла."""
    if not os.path.exists(JSON_DB_PATH):
        init_json_db()
    with open(JSON_DB_PATH, 'r') as f:
        return json.load(f)

def save_data(data):
    """Сохраняет данные в JSON-файл с резервным копированием."""
    # Создаём резервную копию перед записью
    backup_path = f"{JSON_DB_PATH}.backup"
    if os.path.exists(JSON_DB_PATH):
        shutil.copy(JSON_DB_PATH, backup_path)
        logging.info(f"Резервная копия создана: {backup_path}")

    # Сохраняем данные
    with open(JSON_DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)
    logging.info(f"Данные успешно сохранены в {JSON_DB_PATH}")


TIME_OFFSET = timedelta(hours=3)
# --- Напоминания ---
async def send_reminders(application: Application):
    """Отправляет напоминания за 1 и за 24 часа до занятия."""
    logging.info("Функция send_reminders запущена.")  # Лог начала выполнения
    data = load_data()
    now = datetime.now() + TIME_OFFSET  # Корректируем текущее время
    logging.info(f"Текущее время (с учетом смещения): {now}")

    for user_id, schedule in data.get("schedule", {}).items():
        logging.info(f"Обрабатываем расписание для пользователя: {user_id}")
        for entry in schedule:
            lesson_time = parse_lesson_datetime(entry["day"], entry["time"])
            if not lesson_time:
                logging.warning(f"Некорректное время или день: {entry}")
                continue

            time_diff = lesson_time - now
            logging.info(
                f"Проверяем занятие: {entry['description']} в {entry['time']} ({entry['day']}). "
                f"До занятия: {time_diff.total_seconds() / 3600:.2f} часов."
            )

            # Напоминание за 24 часа
            if 23 <= time_diff.total_seconds() / 3600 <= 24 and not entry.get("reminder_sent_24h"):
                logging.info(f"Отправляем напоминание за 24 часа для пользователя {user_id}.")
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: Завтра в {entry['time']} у вас {entry['description']}."
                )
                entry["reminder_sent_24h"] = True

            # Напоминание за 1 час
            elif 0 < time_diff.total_seconds() / 3600 <= 1 and not entry.get("reminder_sent_1h"):
                logging.info(f"Отправляем напоминание за 1 час для пользователя {user_id}.")
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание: Через 1 час в {entry['time']} у вас {entry['description']}."
                )
                entry["reminder_sent_1h"] = True

    save_data(data)
    logging.info("Завершено выполнение send_reminders. Данные сохранены.")




def parse_lesson_datetime(day: str, time: str):
    """Парсит день недели и время в объект datetime."""
    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    if day not in valid_days:
        return None

    day_index = valid_days.index(day)
    now = datetime.now()
    target_date = now + timedelta(days=(day_index - now.weekday()) % 7)
    try:
        lesson_time = datetime.strptime(time, "%H:%M").time()
        return datetime.combine(target_date, lesson_time)
    except ValueError:
        return None


# --- Команды ---
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user = update.effective_user
    data = load_data()

    # Добавляем пользователя
    data["users"][str(user.id)] = {"username": user.username, "first_name": user.first_name}
    save_data(data)

    if user.id == ADMIN_ID:
        admin_keyboard = [
            ["Добавить расписание"],
            ["Ученики", "Просмотр расписания всех"],
            ["Редактировать расписание", "Сбросить к стандартному"]
        ]
        await update.message.reply_text(
            "Вы зарегистрированы как администратор! Выберите команду:",
            reply_markup=ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        )
    else:
        user_keyboard = [["Мое расписание"]]
        await update.message.reply_text(
            "Вы зарегистрированы! Вы будете получать напоминания о занятиях.",
            reply_markup=ReplyKeyboardMarkup(user_keyboard, resize_keyboard=True)
        )


async def students(update: Update, _):
    """Отображает список всех учеников."""
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("Список учеников пуст.")
        return

    students_text = "Список учеников:\n"
    for info in data["users"].values():
        students_text += f"{info['first_name']} (@{info['username']})\n"
    await update.message.reply_text(students_text)


async def view_all_schedules(update: Update, _):
    """Отображает расписание всех учеников."""
    data = load_data()
    if not data["schedule"]:
        await update.message.reply_text("Расписание пусто.")
        return

    schedule_text = "Расписание всех учеников:\n"
    for user_id, schedule in data["schedule"].items():
        user_info = data["users"].get(user_id, {})
        username = user_info.get("username", "Неизвестно")
        first_name = user_info.get("first_name", "Неизвестно")
        schedule_text += f"{first_name} (@{username}):\n"
        for entry in schedule:
            schedule_text += f"  {entry['day']} {entry['time']} - {entry['description']}\n"
    await update.message.reply_text(schedule_text)


async def add_schedule(update: Update, context: CallbackContext):
    """Добавляет расписание для нескольких учеников."""
    if not context.args:
        await update.message.reply_text(
            "Использование: /schedule\n"
            "@username день предмет время1 время2 ...\n\n"
            "Пример:\n"
            "/schedule @ivan123 Понедельник Математика 10:00 14:00"
        )
        return

    lines = " ".join(context.args).split("\n")
    data = load_data()
    messages = []

    # Проверка наличия ключа schedule
    if "schedule" not in data:
        logging.warning("Ключ 'schedule' отсутствует, создаю...")
        data["schedule"] = {}

    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 4:
            messages.append(f"Ошибка: недостаточно данных в строке: {line}")
            logging.warning(f"Недостаточно данных в строке: {line}")
            continue

        username, day, subject, *times = parts

        if day not in valid_days:
            messages.append(f"Ошибка: некорректный день недели: {day}")
            logging.warning(f"Некорректный день недели: {day}")
            continue

        user_id = next((uid for uid, info in data["users"].items() if info["username"] == username.lstrip('@')), None)
        if not user_id:
            messages.append(f"Ошибка: пользователь {username} не найден.")
            logging.warning(f"Пользователь {username} не найден.")
            continue

        # Добавление расписания
        data["schedule"].setdefault(user_id, [])
        for time in times:
            try:
                # Проверка формата времени
                datetime.strptime(time, "%H:%M")
                data["schedule"][user_id].append({
                    "day": day,
                    "time": time,
                    "description": subject,
                    "reminder_sent_1h": False,
                    "reminder_sent_24h": False
                })
            except ValueError:
                messages.append(f"Ошибка: некорректный формат времени {time} для {username}")
                logging.warning(f"Некорректный формат времени {time} для {username}")
                continue

        messages.append(f"Добавлено: {username} - {day} - {subject} в {', '.join(times)}")

    # Сохранение данных
    save_data(data)
    logging.info(f"Данные сохранены: {data}")
    await update.message.reply_text("\n".join(messages))


async def my_schedule(update: Update, _):
    """Отображает расписание ученика."""
    user_id = str(update.effective_user.id)
    data = load_data()

    schedule = data.get("schedule", {}).get(user_id, [])
    if not schedule:
        await update.message.reply_text("Ваше расписание пусто.")
        return

    schedule_text = "Ваше расписание:\n"
    for entry in schedule:
        schedule_text += f"{entry['day']} {entry['time']} - {entry['description']}\n"
    await update.message.reply_text(schedule_text)


async def edit_schedule(update: Update, context: CallbackContext):
    """Позволяет администратору редактировать расписание конкретного пользователя."""
    data = load_data()

    # Проверка: начат ли режим редактирования
    if "edit_mode" not in context.user_data:
        # Создаем клавиатуру с пользователями
        keyboard = [[f"@{info['username']}"] for info in data["users"].values()]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        # Сообщение с выбором пользователя
        await update.message.reply_text(
            "Выберите пользователя для редактирования расписания:",
            reply_markup=reply_markup
        )
        context.user_data["edit_mode"] = True  # Включаем режим редактирования
        return

    # Получить выбранного пользователя
    username = update.message.text.lstrip("@")
    user_id = next((uid for uid, info in data["users"].items() if info["username"] == username), None)

    if not user_id:
        await update.message.reply_text("Пользователь не найден. Попробуйте снова.")
        return

    # Сохраняем ID пользователя для редактирования
    context.user_data["edit_user"] = user_id
    schedule = data["schedule"].get(user_id, [])

    # Проверяем, есть ли расписание у выбранного пользователя
    if not schedule:
        await update.message.reply_text(f"У пользователя @{username} нет расписания.")
    else:
        schedule_text = "Текущее расписание:\n"
        for i, entry in enumerate(schedule, 1):
            schedule_text += f"{i}. {entry['day']} {entry['time']} - {entry['description']}\n"

        await update.message.reply_text(
            f"Текущее расписание пользователя @{username}:\n{schedule_text}\n\n"
            "Введите новое расписание в формате:\n"
            "день предмет время1 время2 ...\n\nПример:\n"
            "Понедельник Математика 10:00 14:00"
        )

    # Включаем режим ожидания нового расписания
    context.user_data["awaiting_new_schedule"] = True

async def handle_new_schedule(update: Update, context: CallbackContext):
    """Обрабатывает новое расписание пользователя."""
    if "awaiting_new_schedule" not in context.user_data:
        return

    user_id = context.user_data["edit_user"]
    data = load_data()

    # Удаляем старое расписание
    data["schedule"][user_id] = []

    # Парсим новое расписание
    lines = update.message.text.split("\n")
    valid_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    messages = []

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 3:
            messages.append(f"Ошибка: недостаточно данных в строке: {line}")
            continue

        day, subject, *times = parts
        if day not in valid_days:
            messages.append(f"Ошибка: некорректный день недели: {day}")
            continue

        for time in times:
            try:
                datetime.strptime(time, "%H:%M")
                data["schedule"][user_id].append({
                    "day": day,
                    "time": time,
                    "description": subject,
                    "reminder_sent_1h": False,
                    "reminder_sent_24h": False
                })
            except ValueError:
                messages.append(f"Ошибка: некорректный формат времени {time}")
                continue

    # Сохраняем данные
    save_data(data)
    messages.append("Новое расписание успешно сохранено!")
    await update.message.reply_text("\n".join(messages))

    # Сброс режима редактирования
    context.user_data.pop("edit_mode", None)
    context.user_data.pop("awaiting_new_schedule", None)
    context.user_data.pop("edit_user", None)

async def reset_to_standard_schedule(update: Update, _):
    """Сбрасывает расписание к стандартному и сохраняет изменения."""
    data = load_data()

    if "standard_schedule" in data:
        # Сбрасываем расписание
        data["schedule"] = data["standard_schedule"].copy()
        save_data(data)  # Сохраняем изменения
        await update.message.reply_text("Расписание успешно сброшено к стандартному!")
    else:
        await update.message.reply_text("Стандартное расписание не задано. Сброс невозможен.")

# --- Основная функция ---
def main():
    init_json_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Планировщик задач
    scheduler.add_job(
        send_reminders,
        CronTrigger(minute="*/10"),  # Запуск каждые 10 минут
        args=[application]
    )
    scheduler.add_job(
        reset_to_standard_schedule,
        CronTrigger(day_of_week="sat", hour=23, minute=59)  # Сброс каждую субботу
    )
    scheduler.start()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))
    application.add_handler(CommandHandler("view_all_schedules", view_all_schedules))
    application.add_handler(CommandHandler("schedule", add_schedule))
    application.add_handler(CommandHandler("my_schedule", my_schedule))
    application.add_handler(CommandHandler("edit_schedule", edit_schedule))

    # Обработчик для текстовых сообщений (режим редактирования)
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_new_schedule))

    logging.info("Бот запущен.")
    application.run_polling()



