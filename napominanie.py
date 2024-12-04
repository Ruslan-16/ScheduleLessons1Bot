from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext
import boto3
import json
import os
import logging

# Настройки для S3
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', '0CLS24Z09YQL8UJLQCQQ')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', '9GcBHRJY97YmWCHe0gXPrJnKgsFC8vqiyoT5GZPL')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', '8df8e63e-raspisanie')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'https://s3.timeweb.cloud')

s3_client = boto3.client(
    's3',
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT_URL
)

# Настройки для Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Включаем логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Функция для старта бота
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('Привет! Я бот для управления расписанием.')

# Функция для создания кнопок
async def show_buttons(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Добавить расписание", callback_data='add_schedule')],
        [InlineKeyboardButton("Ученики", callback_data='students')],
        [InlineKeyboardButton("Редактировать расписание", callback_data='edit_schedule')],
        [InlineKeyboardButton("Просмотр расписания", callback_data='view_schedule')],
        [InlineKeyboardButton("Сброс редактирования", callback_data='reset_editing')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)

# Функция обработки кнопок
async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == 'add_schedule':
        await query.edit_message_text(text="Вы выбрали: Добавить расписание.")
    elif query.data == 'students':
        await query.edit_message_text(text="Вы выбрали: Ученики.")
    elif query.data == 'edit_schedule':
        await query.edit_message_text(text="Вы выбрали: Редактировать расписание.")
    elif query.data == 'view_schedule':
        await query.edit_message_text(text="Вы выбрали: Просмотр расписания.")
    elif query.data == 'reset_editing':
        await query.edit_message_text(text="Вы выбрали: Сброс редактирования.")

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
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_buttons))
    application.add_handler(CallbackQueryHandler(button))

    # Запуск бота
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
