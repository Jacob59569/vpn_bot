import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F

TOKEN = os.getenv("TELEGRAM_TOKEN")

# Настраиваем логирование, чтобы видеть все в консоли
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# Обработчик команды /start
@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    log.info(f"Received /start from user {message.from_user.id}")
    kb = [
        [types.InlineKeyboardButton(text="Нажми меня!", callback_data="test_button_pressed")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("Привет! Нажми на кнопку:", reply_markup=keyboard)


# Обработчик ЛЮБОГО нажатия на инлайн-кнопку
@dp.callback_query(F.data)  # F.data ловит любой callback, у которого есть data
async def button_press_handler(call: types.CallbackQuery):
    log.info(f"Received callback '{call.data}' from user {call.from_user.id}")

    # Обязательно "отвечаем" на callback, чтобы у пользователя пропали "часики" на кнопке
    await call.answer(text="Нажатие обработано!", show_alert=False)

    # Отправляем новое сообщение в чат
    await call.message.answer(f"Вы нажали на кнопку! Данные: {call.data}")


# Главная функция запуска
async def main():
    log.info("Starting bot...")
    # Удаляем вебхук и ПРОПУСКАЕМ все старые обновления
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем polling, передавая боту dispatcher
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")