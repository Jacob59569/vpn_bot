import os
import asyncio
import logging
import json
import uuid
import docker
from datetime import datetime

# --- Импорты ---
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, select

# ==========================================================
#                  КОНФИГУРАЦИЯ
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

# --- Загружаем все из .env файла ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SERVER_ADDRESS = os.getenv("VLESS_SERVER_ADDRESS")
VPN_PASSWORD = os.getenv("VPN_PASSWORD")
REALITY_PUBLIC_KEY = os.getenv("REALITY_PUBLIC_KEY")
REALITY_PRIVATE_KEY = os.getenv("REALITY_PRIVATE_KEY")

# --- Настройки ключей и путей ---
VLESS_GRPC_PORT = 443
VLESS_GRPC_REMARKS = "ShieldVPN_Standard(gRPC)"
VLESS_REALITY_PORT = 8443
VLESS_REALITY_REMARKS = "ShieldVPN_MaxSpeed(REALITY)"
XRAY_CONFIG_PATH = "/app/xray_config/config.json"
REALITY_SNI = "www.yahoo.com"
REALITY_SHORT_ID = "ca3be9b8"

# ==========================================================
#                  БАЗА ДАННЫХ
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


async def init_db():
    os.makedirs("./database", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ==========================================================
#                  УПРАВЛЕНИЕ XRAY
# ==========================================================
async def update_xray_config_and_restart():
    """Генерирует полный конфиг из БД и перезапускает Xray."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        active_users = result.scalars().all()

    clients = [{"id": user.client_uuid, "email": f"user_{user.telegram_id}"} for user in active_users]

    full_config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"listen": "0.0.0.0", "port": 10000, "protocol": "vless", "tag": "vless-grpc",
             "settings": {"clients": clients, "decryption": "none"},
             "streamSettings": {"network": "grpc", "security": "none", "grpcSettings": {"serviceName": "vless-grpc"}}},
            {"listen": "0.0.0.0", "port": 8443, "protocol": "vless", "tag": "vless-reality",
             "settings": {"clients": clients, "decryption": "none"},
             "streamSettings": {"network": "tcp", "security": "reality",
                                "realitySettings": {"show": False, "dest": "yahoo.com:443", "xver": 0,
                                                    "serverNames": ["yahoo.com"], "privateKey": REALITY_PRIVATE_KEY,
                                                    "shortIds": [REALITY_SHORT_ID]}}}
        ],
        "outbounds": [{"protocol": "freedom"}]
    }

    try:
        os.makedirs(os.path.dirname(XRAY_CONFIG_PATH), exist_ok=True)
        with open(XRAY_CONFIG_PATH, 'w') as f:
            json.dump(full_config, f, indent=4)
        log.info(f"Generated new Xray config with {len(clients)} users.")

        client = docker.from_env()
        container = client.containers.get('vpn_xray')
        container.restart()
        log.info("Xray container restarted successfully to apply new config.")
        return True
    except Exception as e:
        log.error(f"Failed to update or reload Xray: {e}")
        return False


# ==========================================================
#                  ОСНОВНАЯ ЛОГИКА ГЕНЕРАЦИИ
# ==========================================================
async def create_or_get_user_keys(telegram_id: int):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()

        if not user:
            log.info(f"Creating new user for telegram_id: {telegram_id}")
            client_uuid = str(uuid.uuid4())
            new_user = User(telegram_id=telegram_id, client_uuid=client_uuid)
            db.add(new_user)
            await db.commit()

            # После добавления пользователя в БД, обновляем конфиг Xray
            success = await update_xray_config_and_restart()
            if not success:
                raise Exception("Could not update Xray config")
            uuid_to_use = new_user.client_uuid
        else:
            log.info(f"Found existing user for telegram_id: {telegram_id}")
            uuid_to_use = user.client_uuid

    grpc_link = (f"vless://{uuid_to_use}@{SERVER_ADDRESS}:{VLESS_GRPC_PORT}?"
                 f"type=grpc&serviceName=vless-grpc&security=tls&sni={SERVER_ADDRESS}"
                 f"#{VLESS_GRPC_REMARKS}")
    reality_link = (f"vless://{uuid_to_use}@{SERVER_ADDRESS}:{VLESS_REALITY_PORT}?"
                    f"type=tcp&security=reality&fp=firefox&pbk={REALITY_PUBLIC_KEY}"
                    f"&sni=yahoo.com&sid=ca3be9b8&spx=%2F"
                    f"#{VLESS_REALITY_REMARKS}")

    return grpc_link, reality_link


# ==========================================================
#                  ТЕЛЕГРАМ-БОТ
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
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Добро пожаловать!", reply_markup=get_main_keyboard())


@dp.message(F.text == "🔑 Получить/показать ключ")
async def request_password(message: types.Message, state: FSMContext):
    await state.set_state(GenKeyStates.waiting_for_password)
    await message.answer("Введите пароль:", reply_markup=types.ReplyKeyboardRemove())


@dp.message(GenKeyStates.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text == VPN_PASSWORD:
        await message.answer("✅ Пароль верный! Генерирую ключи...", reply_markup=get_main_keyboard())
        try:
            grpc_link, reality_link = await create_or_get_user_keys(message.from_user.id)
            response_text = (
                "✅ Ваши ключи готовы!\n\n"
                "1️⃣ **Стандартный ключ (gRPC):**\n"
                f"<code>{grpc_link}</code>\n\n"
                "2️⃣ **Скоростной ключ (REALITY):**\n"
                f"<code>{reality_link}</code>"
            )
            await message.answer(response_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"Error during key generation for user {message.from_user.id}: {e}")
            await message.answer("❌ Произошла ошибка. Сообщите администратору.")
    else:
        await message.answer("❌ Неверный пароль.", reply_markup=get_main_keyboard())


@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    await message.answer("<b>ShieldVPN Bot</b>\n\nБот для выдачи ключей.")


async def main():
    await init_db()
    # Генерируем конфиг при старте, чтобы Xray запустился с актуальными пользователями
    await update_xray_config_and_restart()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        log.info("Starting bot...")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")