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

# --- НОВЫЕ ИМПОРТЫ для состояний (FSM) ---
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ==========================================================
#                  КОНФИГУРАЦИЯ
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000/generate"

# --- Конфигурация VLESS ---
VLESS_SERVER_ADDRESS = "shieldvpn.ru"
VLESS_GRPC_PORT = 443
VLESS_GRPC_REMARKS = "ShieldVPN"


# --- Настройки для VLESS + TCP + REALITY ---
VLESS_REALITY_PORT = 8443
VLESS_REALITY_REMARKS = "ShieldVPN_MaxSpeed(REALITY)"
REALITY_PUBLIC_KEY = "8PSiSpiSdXQLCGVXszWueRRsqflMboBXBFAx7MDLTjo"
REALITY_PRIVATE_KEY = "WDCdXqoRh7xmCDK5ZRkdJc4PrXq9x8N2ZvwFtRFMS34"
REALITY_SNI = "www.yahoo.com"
REALITY_SHORT_ID = "ca3be9b8" # Можете сгенерировать свой: openssl rand -hex 4


# --- ИСПРАВЛЕННЫЙ ПУТЬ ---
XRAY_CONFIG_PATH = "/app/config.json"  # Путь к конфигу Xray, который мы смонтировали
USER_DB_PATH = "/app/user_database.json"

# --- НОВИНКА: Определяем состояния для нашего FSM ---
class GenKeyStates(StatesGroup):
    waiting_for_password = State() # Состояние ожидания пароля

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
    """ИЗМЕНЕНО: Добавляет пользователя в ОБА inbound'а в конфиге."""
    try:
        with open(XRAY_CONFIG_PATH, 'r+') as f:
            config = json.load(f)
            new_client = {"id": user_uuid, "email": email}

            # Проходим по всем инбаундам и добавляем клиента
            for inbound in config.get('inbounds', []):
                if 'clients' not in inbound.get('settings', {}):
                    inbound['settings']['clients'] = []
                inbound['settings']['clients'].append(new_client)

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
            log.info(f"Successfully added user {email} to ALL inbounds in xray config.")
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


@app.post("/generate")
async def generate_key(user_info: dict):
    telegram_id_str = str(user_info.get("telegram_id"))
    user_db = get_user_db()

    if telegram_id_str in user_db:
        user_uuid = user_db[telegram_id_str]
        log.info(f"User {telegram_id_str} already has a key. Returning existing UUID: {user_uuid}")
    else:
        log.info(f"User {telegram_id_str} does not have a key. Generating a new one.")
        user_uuid = str(uuid.uuid4())
        email = f"user_{telegram_id_str}"
        add_user_to_xray_config(user_uuid=user_uuid, email=email)
        user_db[telegram_id_str] = user_uuid
        save_user_db(user_db)

    # --- ИЗМЕНЕНО: Формируем и возвращаем ДВА ключа ---
    grpc_link = (f"vless://{user_uuid}@{VLESS_SERVER_ADDRESS}:{VLESS_GRPC_PORT}?"
                 f"type=grpc&serviceName=vless-grpc&security=tls&sni={VLESS_SERVER_ADDRESS}"
                 f"#{VLESS_GRPC_REMARKS}")

    reality_link = (f"vless://{user_uuid}@{VLESS_SERVER_ADDRESS}:{VLESS_REALITY_PORT}?"
                    f"type=tcp&security=reality&fp=firefox&pbk={REALITY_PUBLIC_KEY}"
                    f"&sni={REALITY_SNI}&sid={REALITY_SHORT_ID}&spx=%2F"
                    f"#{VLESS_REALITY_REMARKS}")

    return {"grpc_link": grpc_link, "reality_link": reality_link}


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
async def command_start_handler(message: types.Message, state: FSMContext):
    # Сбрасываем состояние пользователя, если он был в процессе ввода пароля
    await state.clear()
    log.info(f"Received /start from user {message.from_user.id} ({message.from_user.full_name})")
    await message.answer(
        "Добро пожаловать! 👋\n\n"
        "Я ваш личный помощник для получения доступа к VPN. "
        "Используйте кнопки меню внизу для навигации.",
        reply_markup=get_main_keyboard()
    )

# НОВЫЙ ОБРАБОТЧИК для текстовой кнопки "Получить VLESS ключ"
@dp.message(F.text == "🔑 Получить VLESS ключ")
async def request_key_handler(message: types.Message, state: FSMContext):
    log.info(f"User {message.from_user.id} requested a key, asking for password.")
    # Устанавливаем состояние "ожидание пароля" для этого пользователя
    await state.set_state(GenKeyStates.waiting_for_password)
    await message.answer(
        "Для получения ключа, пожалуйста, введите пароль:",
        # Убираем клавиатуру, чтобы пользователь не нажал что-то другое
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(GenKeyStates.waiting_for_password)
async def password_entered_handler(message: types.Message, state: FSMContext):
    # Захардкодим пароль. В реальном проекте его лучше брать из переменных окружения.
    CORRECT_PASSWORD = "1234"

    if message.text == CORRECT_PASSWORD:
        log.info(f"User {message.from_user.id} entered correct password.")
        # Пароль верный, сбрасываем состояние
        await state.clear()

        # Запускаем логику выдачи ключа, отправляя инлайн-кнопку для подтверждения
        kb = [[types.InlineKeyboardButton(text="Да, подтверждаю", callback_data="get_vless_key")]]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
        await message.answer(
            "✅ Пароль верный! Нажмите, чтобы сгенерировать ваш ключ.",
            reply_markup=keyboard
        )
    else:
        log.warning(f"User {message.from_user.id} entered incorrect password.")
        # Пароль неверный, сбрасываем состояние и возвращаем главное меню
        await state.clear()
        await message.answer(
            "❌ Неверный пароль. Попробуйте еще раз.",
            reply_markup=get_main_keyboard()  # Возвращаем основную клавиатуру
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
    await call.answer("Генерирую ключ... Пожалуйста, подождите.")
    user_data_for_api = {"telegram_id": call.from_user.id}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=user_data_for_api) as response:
                log.info(f"Internal API request to {API_URL} returned status: {response.status}")
                if response.status == 200:
                    # --- ИЗМЕНЕНО: Парсим JSON и форматируем сообщение с ДВУМЯ ключами ---
                    data = await response.json()
                    grpc_link = data.get("grpc_link")
                    reality_link = data.get("reality_link")

                    response_text = (
                        "✅ Ваши ключи готовы!\n\n"
                        "1️⃣ **Стандартный ключ (gRPC):**\n"
                        "Надежный, маскируется под сайт. Используйте, если другие не работают.\n"
                        f"<code>{grpc_link}</code>\n\n"
                        "2️⃣ **Скоростной ключ (REALITY):**\n"
                        "Максимальная производительность и лучший обход блокировок.\n"
                        f"<code>{reality_link}</code>"
                    )
                    await call.message.answer(response_text)
                else:
                    error_text = await response.text()
                    await call.message.answer(f"❌ Не удалось сгенерировать ключ. Ошибка: {error_text}")
        except Exception as e:
            log.exception(f"An critical error occurred: {e}")
            await call.message.answer("❌ Произошла критическая ошибка. Сообщите администратору.")

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