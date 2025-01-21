
FROM python:3.9-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем только файлы проекта в контейнер
COPY . /app

# Копируем файл .env в контейнер
COPY .env /app/.env

# Устанавливаем pip и зависимости
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Указываем порт (если требуется)
EXPOSE 5000

# Запуск приложения
CMD ["python", "napominanie.py"]

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
