import os
import requests
from telebot import TeleBot, types

TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_handler(message):
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton(text="Получить VLESS ключ", callback_data="get_vless")
    markup.add(btn)
    bot.send_message(message.chat.id, "Нажми кнопку, чтобы получить ключ:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "get_vless")
def callback_handler(call):
    bot.answer_callback_query(call.id)  # обязательно подтверждаем callback

    try:
        res = requests.post("http://localhost:8000/generate")
        res.raise_for_status()
        bot.send_message(call.message.chat.id, res.text)
    except Exception as e:
        print(f"Ошибка при вызове API: {e}")
        bot.send_message(call.message.chat.id, "Ошибка генерации ключа")

if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()