import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
import boto3
import json
import os

# Получение значений из переменных окружения
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', '0CLS24Z09YQL8UJLQCQQ')  # замените на свой ключ доступа, если не используете переменные окружения
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', '9GcBHRJY97YmWCHe0gXPrJnKgsFC8vqiyoT5GZPL')  # замените на свой секретный ключ
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', '8df8e63e-raspisanie')  # имя вашего бакета
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'https://s3.timeweb.cloud')  # endpoint для TimeWeb S3

# Настройки для S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT_URL
)

# Настройки для Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Включаем логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Функция для старта бота
def start(update: Update, context: CallbackContext):
    update.message.reply_text('Привет! Я бот для управления расписанием.')

# Функция для создания кнопок
def show_buttons(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Добавить расписание", callback_data='add_schedule')],
        [InlineKeyboardButton("Ученики", callback_data='students')],
        [InlineKeyboardButton("Редактировать расписание", callback_data='edit_schedule')],
        [InlineKeyboardButton("Просмотр расписания", callback_data='view_schedule')],
        [InlineKeyboardButton("Сброс редактирования", callback_data='reset_editing')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Выберите действие:', reply_markup=reply_markup)

# Функция обработки кнопок
def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    # Обрабатываем нажатия кнопок
    if query.data == 'add_schedule':
        query.edit_message_text(text="Вы выбрали: Добавить расписание.")
    elif query.data == 'students':
        query.edit_message_text(text="Вы выбрали: Ученики.")
    elif query.data == 'edit_schedule':
        query.edit_message_text(text="Вы выбрали: Редактировать расписание.")
    elif query.data == 'view_schedule':
        query.edit_message_text(text="Вы выбрали: Просмотр расписания.")
    elif query.data == 'reset_editing':
        query.edit_message_text(text="Вы выбрали: Сброс редактирования.")

# Функция для получения расписания из S3
def get_schedule_from_s3():
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key='schedule.json')
        schedule_data = json.loads(response['Body'].read().decode('utf-8'))
        return schedule_data
    except Exception as e:
        logger.error(f"Ошибка при получении расписания из S3: {e}")
        return {}

# Функция для сохранения расписания в S3
def save_schedule_to_s3(schedule_data):
    try:
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key='schedule.json', Body=json.dumps(schedule_data))
    except Exception as e:
        logger.error(f"Ошибка при сохранении расписания в S3: {e}")

# Главная функция для запуска бота
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Обработчики команд
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", show_buttons))
    dp.add_handler(CallbackQueryHandler(button))

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
