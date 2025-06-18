#!/bin/bash

# Запускаем uvicorn в фоновом режиме
# Убедитесь, что в main.py есть объект `app = FastAPI()`
# и что имя файла с FastAPI - main.py
echo "Starting FastAPI server in background..."
uvicorn main:app --host 0.0.0.0 --port 8000 &

# Запускаем Telegram-бота в основном режиме
# Эта команда будет держать контейнер "живым"
echo "Starting Telegram bot in foreground..."
python main.py