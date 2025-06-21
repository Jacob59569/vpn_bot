FROM python:3.11-slim

RUN apt-get update && apt-get install -y procps && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код
COPY . .

# Даем права на исполнение нашему скрипту
RUN chmod +x ./start.sh

# Запускаем контейнер с помощью нашего скрипта
CMD ["./start.sh"]