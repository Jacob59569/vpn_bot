FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Docker CLI и Docker Compose
RUN apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin

# Устанавливаем Python-зависимости
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения И docker-compose.yml
COPY app/ .
COPY docker-compose.yml .
RUN chmod +x ./start.sh

# Запускаем приложение
CMD ["./start.sh"]