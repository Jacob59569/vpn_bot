#!/bin/bash
set -e

echo "Starting FastAPI server in background..."
uvicorn main:app --host 0.0.0.0 --port 8000 > /app/uvicorn.log 2>&1 &

# Небольшая пауза, чтобы дать API время запуститься
sleep 2

echo "Starting Telegram bot..."
exec python main.py