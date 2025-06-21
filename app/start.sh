#!/bin/bash

# Устанавливаем флаг -e, чтобы скрипт завершился при любой ошибке
set -e

# Проверяем, существует ли файл main.py
if [ ! -f "main.py" ]; then
    echo "Error: main.py not found!"
    exit 1
fi

# Запускаем uvicorn в фоновом режиме
# Перенаправляем его вывод в лог-файл, чтобы видеть ошибки
echo "Starting FastAPI server in background..."
uvicorn main:app --host 0.0.0.0 --port 8000 > /app/uvicorn.log 2>&1 &

# Даем uvicorn секунду на запуск
sleep 1

# Проверяем, запустился ли процесс
if ! pgrep -f "uvicorn main:app"; then
    echo "!!! FastAPI server FAILED to start. Check uvicorn.log for errors. !!!"
    cat /app/uvicorn.log
    exit 1
else
    echo "FastAPI server started successfully."
fi


# Запускаем Telegram-бота в основном режиме
echo "Starting Telegram bot..."
exec python main.py