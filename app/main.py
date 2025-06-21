import os
import asyncio
import logging
import uuid
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
from sqlalchemy import Column, Integer, String, DateTime, Boolean, select
import aiohttp

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

# --- Настройки для ключей и API ---
VLESS_GRPC_PORT = 443
VLESS_GRPC_REMARKS = "ShieldVPN_Standard(gRPC)"
VLESS_REALITY_PORT = 8443
VLESS_REALITY_REMARKS = "ShieldVPN_MaxSpeed(REALITY)"
XRAY_API_URL = "http://vpn_xray:62789"
GRPC_INBOUND_TAG = "vless-grpc"
REALITY_INBOUND_TAG = "vless-reality"

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
#                  УПРАВЛЕНИЕ XRAY через API
# ==========================================================
async def add_user_to_xray(user_uuid: str, email: str):
    user_proto = {"level": 0, "email": email, "id": user_uuid}
    api_endpoint = f"{XRAY_API_URL}/xray.app.proxyman.command.AddUserOperation"

    async with aiohttp.ClientSession() as session:
        # Добавляем в gRPC inbound
        grpc_payload = {"tag": GRPC_INBOUND_TAG, "user": user_proto}
        resp_grpc = await session.post(api_endpoint, json=grpc_payload)

        # Добавляем в REALITY inbound
        reality_payload = {"tag": REALITY_INBOUND_TAG, "user": user_proto}
        resp_reality = await session.post(api_endpoint, json=reality_payload)

        if resp_grpc.status == 200 and resp_reality.status == 200:
            log.info(f"Successfully added user {email} via Xray API.")
            return True
        else:
            log.error(f"Xray API Error: gRPC={await resp_grpc.text()}, REALITY={await resp_reality.text()}")
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
            success = await add_user_to_xray(user_uuid=client_uuid, email=f"user_{telegram_id}")
            if not success:
                raise Exception("Could not add user to Xray")

            new_user = User(telegram_id=telegram_id, client_uuid=client_uuid)
            db.add(new_user)
            await db.commit()
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
                "✅ Ваши ключи готовы:\n\n"
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
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        log.info("Starting bot...")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")