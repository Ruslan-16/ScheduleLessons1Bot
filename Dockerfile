FROM python:3.9-slim 

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY . /app

# Копируем .env файл
COPY .env /app/.env

# Устанавливаем pip и зависимости
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Указываем порт (если требуется)
EXPOSE 5000

# Устанавливаем часовой пояс
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Запуск приложения
CMD ["python", "napominanie.py"]

