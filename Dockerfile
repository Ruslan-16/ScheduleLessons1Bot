FROM python:3.12-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Открываем порт (необязательно, если бот работает только с Telegram)
EXPOSE 5000

# Запуск приложения
CMD ["python", "napominanie.py"]


