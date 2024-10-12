# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файл requirements.txt в контейнер
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы вашего приложения в рабочую директорию контейнера
COPY . .

# Устанавливаем переменную окружения для корректной работы приложения
ENV TELEGRAM_TOKEN=$TELEGRAM_TOKEN
ENV ADMIN_CHAT_ID=$ADMIN_CHAT_ID

# Команда для запуска приложения
CMD ["python", "main.py"]
