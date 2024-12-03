import os
import json
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from dotenv import load_dotenv
import boto3
from botocore.exceptions import NoCredentialsError, EndpointConnectionError

# --- Инициализация окружения ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")

# Настройка клиента S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT_URL
)

S3_JSON_DB_PATH = "bot_data/users.json"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Функции работы с S3 ---
def load_data():
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=S3_JSON_DB_PATH)
        return json.loads(response['Body'].read().decode())
    except s3_client.exceptions.NoSuchKey:
        logger.info("Файл не найден. Создаём новый.")
        return {"users": {}}
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных: {e}")
        raise

def save_data(data):
    try:
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=S3_JSON_DB_PATH, Body=json.dumps(data, indent=4))
        logger.info("Данные успешно сохранены.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных: {e}")

# --- Команды бота ---
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    data = load_data()

    # Регистрируем пользователя
    data["users"][str(user.id)] = {"username": user.username, "first_name": user.first_name}
    save_data(data)

    if str(user.id) == ADMIN_ID:
        await update.message.reply_text("Вы зарегистрированы как администратор!")
    else:
        await update.message.reply_text("Вы зарегистрированы!")

async def students(update: Update, context: CallbackContext):
    data = load_data()
    users = data.get("users", {})
    if not users:
        await update.message.reply_text("Нет зарегистрированных пользователей.")
        return

    message = "Зарегистрированные пользователи:\n"
    for user_id, info in users.items():
        message += f"{info.get('first_name')} (@{info.get('username')})\n"
    await update.message.reply_text(message)

# --- Основная функция ---
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("students", students))

    # Запуск бота
    await application.run_polling()

# --- Запуск ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            logger.info("Бот остановлен.")
