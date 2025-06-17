import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

TOKEN = "7697602760:AAEdu5NLl2UEZYTuyAit3ImiziiVn_vYppE"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🎟️ Выдать VLESS ключ")]],
    resize_keyboard=True
)

@dp.message()
async def handle_message(message: types.Message):
    if message.text == "/start":
        await message.answer("Привет! Нажми кнопку ниже, чтобы получить VLESS ключ.", reply_markup=keyboard)
    elif message.text == "🎟️ Выдать VLESS ключ":
        key = await get_one_key()
        if key:
            await message.answer(f"<b>Вот твой ключ:</b>\n<code>{key}</code>")
        else:
            await message.answer("Ключи закончились 😢")

async def get_one_key():
    return "vless://c96be059-f449-4452-9ee9-a0168cfee87c@37.252.10.195:34755?type=tcp&security=reality&fp=firefox&pbk=6MLVXwtbQrxIzwai3n2jr4McFVB9qBLd5RTn9Fx8bDU&sni=yahoo.com&sid=a8ff4915&spx=%2F#"

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())