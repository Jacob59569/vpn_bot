#!/bin/bash

# Даем другим контейнерам (особенно xray) время на полный запуск
echo "Waiting for other services to start..."
sleep 5

# Теперь запускаем бота
echo "Starting Telegram bot..."
python main.py