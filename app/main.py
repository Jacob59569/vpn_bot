import os
import asyncio
import logging
import aiohttp
import json
import uuid
import docker
from aiogram.utils.keyboard import ReplyKeyboardBuilder

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
USER_DB_PATH = "/app/user_database.json"

# ==========================================================
#                  ЧАСТЬ 1: ЛОГИКА API и VLESS
# ==========================================================
app = FastAPI()


def get_user_db():
    """Читает и возвращает базу данных пользователей."""
    try:
        with open(USER_DB_PATH, 'r') as f:
            # Если файл пуст, возвращаем пустой словарь
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except FileNotFoundError:
        # Если файла нет, создаем его
        with open(USER_DB_PATH, 'w') as f:
            json.dump({}, f)
        return {}


def save_user_db(db):
    """Сохраняет базу данных пользователей."""
    with open(USER_DB_PATH, 'w') as f:
        json.dump(db, f, indent=4)


def add_user_to_xray_config(user_uuid: str, email: str):
    """Добавляет нового пользователя в конфиг Xray и перезапускает сервис."""
    try:
        with open(XRAY_CONFIG_PATH, 'r+') as f:
            config = json.load(f)
            inbound_settings = config['inbounds'][0]['settings']
            if 'clients' not in inbound_settings:
                inbound_settings['clients'] = []

            # Добавляем нового клиента (мы уже знаем, что его там нет)
            new_client = {"id": user_uuid, "email": email}
            inbound_settings['clients'].append(new_client)

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
            log.info(f"Successfully added user {email} ({user_uuid}) to xray config.")
    except Exception as e:
        log.error(f"Failed to update Xray config file: {e}")
        raise HTTPException(status_code=500, detail="Could not update Xray configuration.")

    try:
        log.info("Restarting 'vpn_xray' container to apply new config...")
        client = docker.from_env()
        container = client.containers.get('vpn_xray')
        container.restart()
        log.info("Container 'vpn_xray' restarted successfully.")
    except Exception as e:
        log.error(f"Failed to restart xray container: {e}")
        # Продолжаем, но ключ может быть неактивен


def format_vless_link(user_uuid: str):
    """Форматирует VLESS-ссылку по UUID."""
    return (
        f"vless://{user_uuid}@{VLESS_SERVER_ADDRESS}:{VLESS_SERVER_PORT}?"
        f"type=grpc&security=tls&serviceName=vless-grpc&host={VLESS_SERVER_ADDRESS}"
        f"#{VLESS_REMARKS}"
    )


@app.post("/generate")
async def generate_key(user_info: dict):
    telegram_id_str = str(user_info.get("telegram_id"))

    # Загружаем нашу "базу данных"
    user_db = get_user_db()

    # ПРОВЕРКА: есть ли уже ключ у этого пользователя?
    if telegram_id_str in user_db:
        user_uuid = user_db[telegram_id_str]
        log.info(f"User {telegram_id_str} already has a key. Returning existing UUID: {user_uuid}")
        # Просто возвращаем существующий ключ, ничего не меняя и не перезапуская
        return format_vless_link(user_uuid)
    else:
        # СОЗДАНИЕ НОВОГО КЛЮЧА
        log.info(f"User {telegram_id_str} does not have a key. Generating a new one.")
        user_uuid = str(uuid.uuid4())
        email = f"user_{telegram_id_str}"

        # 1. Добавляем пользователя в конфиг Xray и перезапускаем
        add_user_to_xray_config(user_uuid=user_uuid, email=email)

        # 2. Сохраняем связку telegram_id -> vless_uuid в нашу базу
        user_db[telegram_id_str] = user_uuid
        save_user_db(user_db)

        # 3. Возвращаем новый ключ
        return format_vless_link(user_uuid)


# ==========================================================
#                  ЧАСТЬ 2: КОД ТЕЛЕГРАМ-БОТА
# ==========================================================
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

# --- НОВАЯ ЛОГИКА: Создание постоянной клавиатуры ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔑 Получить VLESS ключ")
    builder.button(text="ℹ️ О боте")
    # Указываем, чтобы кнопки располагались по одной в ряду
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- Обработчики ---

# Обработчик команды /start
@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    log.info(f"Received /start from user {message.from_user.id} ({message.from_user.full_name})")
    await message.answer(
        "Добро пожаловать! 👋\n\n"
        "Я ваш личный помощник для получения доступа к VPN. "
        "Используйте кнопки меню внизу для навигации.",
        reply_markup=get_main_keyboard() # <--- Отправляем постоянную клавиатуру
    )

# НОВЫЙ ОБРАБОТЧИК для текстовой кнопки "Получить VLESS ключ"
@dp.message(F.text == "🔑 Получить VLESS ключ")
async def request_key_handler(message: types.Message):
    # Здесь мы создаем инлайн-кнопку для подтверждения, как раньше
    kb = [[types.InlineKeyboardButton(text="Да, сгенерировать ключ", callback_data="get_vless_key")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer(
        "Вы уверены, что хотите получить ключ? "
        "Если у вас уже есть ключ, будет выдан он же.",
        reply_markup=keyboard
    )

# НОВЫЙ ОБРАБОТЧИК для кнопки "О боте"
@dp.message(F.text == "ℹ️ О боте")
async def about_bot_handler(message: types.Message):
    await message.answer(
        "<b>ShieldVPN Bot</b>\n\n"
        "Этот бот создан для автоматической выдачи ключей доступа к приватному VPN-сервису."
    )

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