FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["sh", "-c", "python bot.py & uvicorn api:app --host 0.0.0.0 --port 8000"]