import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import aiohttp

API_URL = "http://localhost:8000/generate"

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    btn = InlineKeyboardButton("Получить VLESS ключ", callback_data="get_vless")
    keyboard.add(btn)
    await message.answer("Нажми кнопку, чтобы получить ключ:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "get_vless")
async def handle_vless(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL) as resp:
            if resp.status == 200:
                text = await resp.text()
                await bot.send_message(callback_query.from_user.id, text)
            else:
                await bot.send_message(callback_query.from_user.id, "Ошибка генерации ключа")

async def main():
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())