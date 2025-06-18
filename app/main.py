import os
import asyncio
import logging
import aiohttp

# --- Импорты для FastAPI ---
from fastapi import FastAPI

# --- Импорты для Aiogram ---
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F

# ==========================================================
#                  ЧАСТЬ 1: КОД FastAPI
# ==========================================================

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

# Создаем экземпляр FastAPI. Uvicorn будет искать именно эту переменную `app`.
app = FastAPI()


@app.post("/generate")
async def generate_key():
    # Здесь должна быть ваша логика генерации ключа
    # Пока что просто вернем тестовый ключ для проверки
    log.info("API endpoint /generate was called")
    return "vless://test-key-from-api-it-works!"


# ==========================================================
#                  ЧАСТЬ 2: КОД ТЕЛЕГРАМ-БОТА
# ==========================================================

# --- Конфигурация ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
# ВАЖНО: Используем localhost, так как бот и API в одном контейнере
API_URL = "http://localhost:8000/generate"

# --- Инициализация Aiogram ---
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())


# --- Обработчики ---

@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    log.info(f"Received /start from user {message.from_user.id} ({message.from_user.full_name})")
    kb = [
        [types.InlineKeyboardButton(text="🔑 Получить VLESS ключ", callback_data="get_vless_key")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("Привет! Нажми на кнопку, чтобы получить новый ключ доступа:", reply_markup=keyboard)


@dp.callback_query(F.data == "get_vless_key")
async def get_vless_key_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    log.info(f"User {user_id} clicked the button to get a VLESS key.")
    await call.answer("Генерирую ключ... Пожалуйста, подождите.")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL) as response:
                log.info(f"Internal API request to {API_URL} returned status: {response.status}")
                if response.status == 200:
                    vless_key = await response.text()
                    response_text = (
                        "✅ Ваш новый ключ готов!\n\n"
                        "Скопируйте его целиком и добавьте в свой клиент:\n\n"
                        f"<code>{vless_key}</code>"
                    )
                    await call.message.answer(response_text)
                else:
                    error_text = await response.text()
                    log.error(f"API returned an error. Status: {response.status}, Body: {error_text}")
                    await call.message.answer("❌ Не удалось сгенерировать ключ. Сервер API вернул ошибку.")
        except Exception as e:
            log.exception(f"An unexpected error occurred: {e}")
            await call.message.answer("❌ Произошла непредвиденная ошибка. Пожалуйста, сообщите администратору.")


# --- Функция запуска БОТА ---
# Она будет вызвана из __main__
async def run_bot():
    log.info("Starting bot polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


# Основной блок запуска
if __name__ == "__main__":
    # Этот блок будет запущен командой `python main.py` из скрипта start.sh
    # Uvicorn будет запущен отдельно этим же скриптом.
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")