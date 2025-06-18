import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router

import aiohttp

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000/generate"

logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# /start
@router.message(CommandStart())
async def start(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить VLESS ключ", callback_data="get_vless")]
        ]
    )
    await message.answer("Нажми кнопку, чтобы получить ключ:", reply_markup=keyboard)

# callback на кнопку
@router.callback_query(lambda c: True)  # Ловим все callback
async def any_callback(call: types.CallbackQuery):
    print("Callback received!")
    await bot.answer_callback_query(call.id)
    await call.message.answer("Callback сработал")

# Подключаем router к dispatcher
dp.include_router(router)

# Запуск
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())