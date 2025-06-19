import os
import asyncio
import logging
import aiohttp
import json
import uuid

# --- Импорты для FastAPI ---
from fastapi import FastAPI, HTTPException

# --- Импорты для Aiogram ---
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F

# ==========================================================
#                  КОНФИГУРАЦИЯ
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000/generate"

# --- Конфигурация VLESS ---
VLESS_SERVER_ADDRESS = "shieldvpn.ru"
VLESS_SERVER_PORT = 443
VLESS_REMARKS = "ShieldVPN"
# --- ИСПРАВЛЕННЫЙ ПУТЬ ---
XRAY_CONFIG_PATH = "/app/config.json"  # Путь к конфигу Xray, который мы смонтировали

# ==========================================================
#                  ЧАСТЬ 1: ЛОГИКА API и VLESS
# ==========================================================
app = FastAPI()


def add_user_to_xray_config(user_id: str, email: str):
    try:
        # Используем with open для безопасной работы с файлом
        with open(XRAY_CONFIG_PATH, 'r+') as f:
            config = json.load(f)
            inbound_settings = config['inbounds'][0]['settings']

            # Проверяем, нет ли уже такого пользователя
            client_exists = any(client['id'] == user_id for client in inbound_settings.get('clients', []))
            if client_exists:
                log.info(f"User with ID {user_id} already exists in xray config.")
                return

            # Добавляем нового клиента
            new_client = {"id": user_id, "email": email}
            inbound_settings.setdefault('clients', []).append(new_client)

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
            log.info(f"Successfully added user {email} ({user_id}) to xray config.")

    except (FileNotFoundError, json.JSONDecodeError, KeyError, IndexError) as e:
        log.error(f"Failed to update Xray config: {e}")
        raise HTTPException(status_code=500, detail="Could not update Xray configuration.")


@app.post("/generate")
async def generate_key(user_info: dict):
    # ... (код генерации user_id и добавления в конфиг остается тем же) ...
    user_id = str(uuid.uuid4())
    telegram_user_id = user_info.get("telegram_id", "unknown_user")
    email = f"user_{telegram_user_id}"
    log.info(f"Generating key for Telegram user {telegram_user_id}")
    add_user_to_xray_config(user_id=user_id, email=email)

    # --- НОВАЯ СТРОКА ДЛЯ ГЕНЕРАЦИИ ССЫЛКИ ---
    vless_link = (
        f"vless://{user_id}@{VLESS_SERVER_ADDRESS}:{VLESS_SERVER_PORT}?"
        f"type=ws&security=tls&path=%2Fvless-ws&host={VLESS_SERVER_ADDRESS}&mtu=1420"
        f"#{VLESS_REMARKS}"
    )

    return vless_link


# ==========================================================
#                  ЧАСТЬ 2: КОД ТЕЛЕГРАМ-БОТА
# ==========================================================
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())


@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    log.info(f"Received /start from user {message.from_user.id} ({message.from_user.full_name})")
    kb = [[types.InlineKeyboardButton(text="🔑 Получить VLESS ключ", callback_data="get_vless_key")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("Привет! Нажми на кнопку, чтобы получить новый ключ доступа:", reply_markup=keyboard)


@dp.callback_query(F.data == "get_vless_key")
async def get_vless_key_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    user_fullname = call.from_user.full_name
    log.info(f"User {user_id} ({user_fullname}) clicked the button to get a VLESS key.")
    await call.answer("Генерирую ключ... Пожалуйста, подождите.")

    user_data_for_api = {"telegram_id": user_id, "full_name": user_fullname}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=user_data_for_api) as response:
                log.info(f"Internal API request to {API_URL} returned status: {response.status}")
                if response.status == 200:
                    vless_key = await response.text()
                    vless_key = vless_key.strip('"')
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
        except aiohttp.ClientConnectorError as e:
            log.error(f"Could not connect to the API server at {API_URL}. Error: {e}")
            await call.message.answer("❌ Ошибка подключения к серверу API.\nПожалуйста, сообщите администратору.")
        except Exception as e:
            log.exception(f"An unexpected error occurred while processing request from user {user_id}: {e}")
            await call.message.answer("❌ Произошла непредвиденная ошибка. Попробуйте позже.")


# --- Функция запуска БОТА ---
async def run_bot():
    log.info("Starting bot polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")