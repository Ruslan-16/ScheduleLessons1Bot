# Используем образ Python 3.9
FROM python:3.9

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . /app

# Устанавливаем зависимости
RUN pip install -r requirements.txt

# Открываем порт 5000 (если требуется)
EXPOSE 5000

# Запуск приложения
CMD ["python", "napominanie.py"]
