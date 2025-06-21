# Используем базовый образ Python 3.11-slim
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Добавляем официальный репозиторий Docker
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Устанавливаем Docker CLI и Docker Compose
RUN apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin

# --- ИСПРАВЛЕННЫЕ ПУТИ ---
WORKDIR /app
# Копируем requirements.txt из текущего контекста (./app) в /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код из текущего контекста (./app) в /app
COPY . .
RUN chmod +x ./start.sh

# Запускаем приложение
CMD ["./start.sh"]