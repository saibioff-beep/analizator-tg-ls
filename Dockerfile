FROM python:3.12-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Создаём папку для данных (будет переопределена Volume)
RUN mkdir -p /app/data

# Запуск бота
CMD ["python", "main.py"]