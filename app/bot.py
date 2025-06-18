from telebot import TeleBot, types
import requests
import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_handler(message):
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("Получить VLESS ключ", callback_data="get_vless")
    markup.add(btn)
    bot.send_message(message.chat.id, "Нажми кнопку, чтобы получить ключ:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "get_vless")
def handle_vless(call):
    res = requests.post("http://localhost:8000/generate")
    if res.ok:
        bot.send_message(call.message.chat.id, res.text)
    else:
        bot.send_message(call.message.chat.id, "Ошибка генерации ключа")

if __name__ == "__main__":
    bot.polling()