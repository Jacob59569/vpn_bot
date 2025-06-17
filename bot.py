import logging
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode

TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
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
    async with aiosqlite.connect("vless_keys.db") as db:
        async with db.execute("SELECT id, key FROM keys LIMIT 1") as cursor:
            row = await cursor.fetchone()
            if row:
                key_id, key = row
                await db.execute("DELETE FROM keys WHERE id = ?", (key_id,))
                await db.commit()
                return key
    return None

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())