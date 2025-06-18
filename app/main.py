import os
import asyncio
import logging
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F

# --- Конфигурация ---
TOKEN = "7697602760:AAEdu5NLl2UEZYTuyAit3ImiziiVn_vYppE"
# Используем имя сервиса из docker-compose, а не localhost
API_URL = "http://app:8000/generate"

# Настраиваем логирование, чтобы видеть все в консоли
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

# --- Инициализация Aiogram ---
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)  # Добавим parse_mode для красивого вывода
dp = Dispatcher(storage=MemoryStorage())


# --- Обработчики ---

# Обработчик команды /start
@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    log.info(f"Received /start from user {message.from_user.id} ({message.from_user.full_name})")

    # Создаем клавиатуру с кнопкой
    kb = [
        [types.InlineKeyboardButton(text="🔑 Получить VLESS ключ", callback_data="get_vless_key")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)

    await message.answer("Привет! Нажми на кнопку, чтобы получить новый ключ доступа:", reply_markup=keyboard)


# Обработчик нажатия на кнопку "Получить VLESS ключ"
@dp.callback_query(F.data == "get_vless_key")
async def get_vless_key_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    log.info(f"User {user_id} clicked the button to get a VLESS key.")

    # Сначала отвечаем на callback, чтобы убрать "часики"
    await call.answer("Генерирую ключ... Пожалуйста, подождите.")

    # Создаем сессию для HTTP-запроса
    async with aiohttp.ClientSession() as session:
        try:
            # Отправляем POST-запрос к нашему API
            async with session.post(API_URL) as response:
                log.info(f"API request to {API_URL} returned status: {response.status}")

                if response.status == 200:
                    # Если все успешно, получаем ключ
                    vless_key = await response.text()

                    # Формируем красивое сообщение с ключом
                    response_text = (
                        "✅ Ваш новый ключ готов!\n\n"
                        "Скопируйте его целиком и добавьте в свой клиент:\n\n"
                        f"<code>{vless_key}</code>"
                    )
                    await call.message.answer(response_text)
                else:
                    # Если API вернуло ошибку
                    error_text = await response.text()
                    log.error(f"API returned an error. Status: {response.status}, Body: {error_text}")
                    await call.message.answer("❌ Не удалось сгенерировать ключ. Сервер API вернул ошибку.")

        except aiohttp.ClientConnectorError as e:
            # Если не удалось подключиться к API (самая частая ошибка в Docker)
            log.error(f"Could not connect to the API server at {API_URL}. Error: {e}")
            await call.message.answer(
                "❌ Ошибка подключения к серверу API.\n"
                "Пожалуйста, сообщите администратору."
            )
        except Exception as e:
            # Ловим все остальные возможные ошибки
            log.exception(f"An unexpected error occurred while processing request from user {user_id}: {e}")
            await call.message.answer("❌ Произошла непредвиденная ошибка. Попробуйте позже.")


# --- Функция запуска ---
async def main():
    log.info("Starting bot...")
    # Удаляем вебхук и ПРОПУСКАЕМ все старые обновления
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")