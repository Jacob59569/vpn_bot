# Используем базовый образ Python 3.11-slim
FROM python:3.11-slim

# Устанавливаем системные зависимости, необходимые для добавления репозитория Docker
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Добавляем официальный GPG ключ Docker
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc

# Добавляем сам репозиторий Docker в список источников apt
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Теперь, когда репозиторий добавлен, обновляем список пакетов и устанавливаем docker-ce-cli и плагин compose
RUN apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin

# Устанавливаем Python-зависимости
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения и docker-compose.yml
COPY app/ .
COPY docker-compose.yml .
RUN chmod +x ./start.sh

# Запускаем приложение
CMD ["./start.sh"]