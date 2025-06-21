import os
import asyncio
import logging
import json
import uuid
import hashlib
from datetime import datetime

# --- Импорты ---
# Для веб-сервиса (вебхуков)
from fastapi import FastAPI

# Для Telegram-бота
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Для базы данных
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, select

# Для HTTP-запросов к API Xray
import aiohttp

# ==========================================================
#                  КОНФИГУРАЦИЯ
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

# --- Переменные окружения и константы ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SERVER_ADDRESS = os.getenv("VLESS_SERVER_ADDRESS", "shieldvpn.ru")
VPN_PASSWORD = os.getenv("VPN_PASSWORD", "1234")  # ВАЖНО: Смените пароль!

# --- Настройки ключей ---
VLESS_GRPC_PORT = 443
VLESS_GRPC_REMARKS = "ShieldVPN_Standard(gRPC)"
VLESS_REALITY_PORT = 8443
VLESS_REALITY_REMARKS = "ShieldVPN_MaxSpeed(REALITY)"

# --- Настройки для Xray API и REALITY ---
# ВАЖНО: Вставьте сюда ваши реальные ключи!
REALITY_PUBLIC_KEY = "8PSiSpiSdXQLCGVXszWueRRsqflMboBXBFAx7MDLTjo"
XRAY_API_URL = "http://vpn_xray:62789"  # API Xray слушает на этом порту (внутренняя сеть Docker)
GRPC_INBOUND_TAG = "vless-grpc"
REALITY_INBOUND_TAG = "vless-reality"

# ==========================================================
#                  БАЗА ДАННЫХ (SQLite через SQLAlchemy)
# ==========================================================
DATABASE_URL = "sqlite+aiosqlite:///./database/vpn_users.db"
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    client_uuid = Column(String, unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)


async def init_db():
    os.makedirs("./database", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ==========================================================
#                  УПРАВЛЕНИЕ XRAY через API
# ==========================================================
async def xray_api_request(service_path: str, request_data: dict):
    """Отправляет запрос к gRPC-шлюзу Xray."""
    headers = {'Content-Type': 'application/json'}
    api_endpoint = f"{XRAY_API_URL}/{service_path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_endpoint, headers=headers, json=request_data) as response:
                if response.status == 200:
                    return True
                else:
                    log.error(f"Xray API Error: Status {response.status}, Body: {await response.text()}")
                    return False
    except Exception as e:
        log.error(f"Exception during Xray API call: {e}")
        return False


async def add_user_to_xray(user_uuid: str, email: str):
    """Добавляет пользователя в оба inbound'а через API Xray."""
    user_proto = {"level": 0, "email": email, "id": user_uuid}

    # Добавляем в gRPC inbound
    success_grpc = await xray_api_request(
        "xray.app.proxyman.command.AddUserOperation",
        {"tag": GRPC_INBOUND_TAG, "user": user_proto}
    )
    # Добавляем в REALITY inbound
    success_reality = await xray_api_request(
        "xray.app.proxyman.command.AddUserOperation",
        {"tag": REALITY_INBOUND_TAG, "user": user_proto}
    )

    if success_grpc and success_reality:
        log.info(f"Successfully added user {email} via Xray API.")
        return True
    else:
        log.error(f"Failed to add user {email} to one or more inbounds.")
        return False


# ==========================================================
#                  ОСНОВНАЯ ЛОГИКА ГЕНЕРАЦИИ
# ==========================================================
async def create_or_get_user_keys(telegram_id: int):
    """
    Находит пользователя в БД или создает нового,
    и возвращает его VLESS ключи.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()

        if not user:
            log.info(f"Creating new user for telegram_id: {telegram_id}")
            client_uuid = str(uuid.uuid4())
            # Сначала добавляем пользователя в Xray
            success = await add_user_to_xray(user_uuid=client_uuid, email=f"user_{telegram_id}")
            if not success:
                raise Exception("Could not add user to Xray")

            # Только потом сохраняем в нашу БД
            new_user = User(telegram_id=telegram_id, client_uuid=client_uuid)
            db.add(new_user)
            await db.commit()
            uuid_to_use = new_user.client_uuid
        else:
            log.info(f"Found existing user for telegram_id: {telegram_id}")
            uuid_to_use = user.client_uuid

    # Формируем обе ссылки
    grpc_link = (f"vless://{uuid_to_use}@{SERVER_ADDRESS}:{VLESS_GRPC_PORT}?"
                 f"type=grpc&serviceName=vless-grpc&security=tls&sni={SERVER_ADDRESS}"
                 f"#{VLESS_GRPC_REMARKS}")

    reality_link = (f"vless://{uuid_to_use}@{SERVER_ADDRESS}:{VLESS_REALITY_PORT}?"
                    f"type=tcp&security=reality&fp=firefox&pbk={REALITY_PUBLIC_KEY}"
                    f"&sni=www.yahoo.com&sid=ca3be9b8&spx=%2F"
                    f"#{VLESS_REALITY_REMARKS}")

    return grpc_link, reality_link


# ==========================================================
#                  FastAPI (для будущих вебхуков)
# ==========================================================
app = FastAPI()


# ==========================================================
#                  Telegram-бот
# ==========================================================
class GenKeyStates(StatesGroup):
    waiting_for_password = State()


bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔑 Получить/показать ключ")
    builder.button(text="ℹ️ О боте")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


@dp.message(CommandStart())
async def command_start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Добро пожаловать! 👋\nИспользуйте кнопки меню для навигации.",
        reply_markup=get_main_keyboard()
    )


@dp.message(F.text == "🔑 Получить/показать ключ")
async def request_key_handler(message: types.Message, state: FSMContext):
    await state.set_state(GenKeyStates.waiting_for_password)
    await message.answer(
        "Для получения доступа, пожалуйста, введите пароль:",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(GenKeyStates.waiting_for_password)
async def password_entered_handler(message: types.Message, state: FSMContext):
    if message.text == VPN_PASSWORD:
        await state.clear()
        await message.answer("✅ Пароль верный! Генерирую ваши ключи...", reply_markup=get_main_keyboard())
        try:
            grpc_link, reality_link = await create_or_get_user_keys(message.from_user.id)
            response_text = (
                "✅ Ваши ключи готовы!\n\n"
                "1️⃣ **Стандартный ключ (gRPC):**\n"
                "Надежный, маскируется под сайт.\n"
                f"<code>{grpc_link}</code>\n\n"
                "2️⃣ **Скоростной ключ (REALITY):**\n"
                "Максимальная производительность.\n"
                f"<code>{reality_link}</code>"
            )
            await message.answer(response_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"Error during key generation for user {message.from_user.id}: {e}")
            await message.answer("❌ Произошла ошибка при создании ключа. Сообщите администратору.")
    else:
        await state.clear()
        await message.answer("❌ Неверный пароль. Попробуйте еще раз.", reply_markup=get_main_keyboard())


@dp.message(F.text == "ℹ️ О боте")
async def about_bot_handler(message: types.Message):
    await message.answer("<b>ShieldVPN Bot</b>\n\nЭтот бот создан для автоматической выдачи ключей доступа.")


# ==========================================================
#                  ЗАПУСК
# ==========================================================
async def run_bot():
    """
    Инициализирует базу данных и запускает polling для Telegram-бота.
    """
    # Инициализируем БД при старте
    await init_db()

    # Запускаем бота
    log.info("Starting bot polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


# Этот блок предназначен для запуска командой `python main.py` из скрипта start.sh
# Uvicorn для FastAPI будет запущен отдельно этим же скриптом.
if __name__ == "__main__":
    try:
        # Вызываем правильно определенную функцию run_bot
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")
