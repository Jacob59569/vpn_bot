import os
import asyncio
import logging
import json
import uuid
from datetime import datetime

# --- Импорты для FastAPI ---
from fastapi import FastAPI, HTTPException

# --- Импорты для Docker ---
import docker
from docker.aio import DockerClient

# --- Импорты для Aiogram ---
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram import F

# --- Импорты для SQLAlchemy ---
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

# ==========================================================
#                  КОНФИГУРАЦИЯ
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000/get_or_create_key"
XRAY_CONFIG_PATH = "/app/config.json"
XRAY_CONTAINER_NAME = "vpn_xray"
DATABASE_PATH = "/app/data/users.db"  # Путь к файлу БД внутри volume

VLESS_SERVER_ADDRESS = "shieldvpn.ru"  # Ваш домен
VLESS_SERVER_PORT = 443  # Порт Caddy
VLESS_REMARKS = "ShieldVPN"  # Имя ключа
VLESS_WS_PATH = "/vless-ws"  # Секретный путь

# ==========================================================
#                  ЧАСТЬ 1: БАЗА ДАННЫХ (SQLAlchemy)
# ==========================================================
engine = create_engine(f"sqlite:///{DATABASE_PATH}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    xray_uuid = Column(String, unique=True, nullable=False)
    full_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


# Создаем директорию для БД, если ее нет
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
Base.metadata.create_all(bind=engine)

# ==========================================================
#                  ЧАСТЬ 2: ЛОГИКА API и VLESS
# ==========================================================
app = FastAPI()


async def restart_xray_container():
    try:
        async with DockerClient.from_env() as client:
            log.info(f"Attempting to find container '{XRAY_CONTAINER_NAME}'...")
            container = await client.containers.get(XRAY_CONTAINER_NAME)
            log.info(f"Container found. Restarting...")
            await container.restart()
            log.info(f"Container '{XRAY_CONTAINER_NAME}' restarted successfully.")
            return True
    except docker.errors.NotFound:
        log.error(f"Container '{XRAY_CONTAINER_NAME}' not found.")
    except Exception as e:
        log.error(f"Failed to restart container '{XRAY_CONTAINER_NAME}': {e}")
    return False


def add_user_to_xray_config(user_id: str, email: str) -> bool:
    try:
        with open(XRAY_CONFIG_PATH, 'r+') as f:
            config = json.load(f)
            inbound_settings = config['inbounds'][0]['settings']
            new_client = {"id": user_id, "email": email}
            inbound_settings.setdefault('clients', []).append(new_client)
            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
            log.info(f"Successfully added user {email} ({user_id}) to {XRAY_CONFIG_PATH}")
            return True
    except (FileNotFoundError, json.JSONDecodeError, KeyError, IndexError) as e:
        log.error(f"Failed to update Xray config: {e}")
        return False


def get_vless_link(user_uuid: str) -> str:
    return (
        f"vless://{user_uuid}@{VLESS_SERVER_ADDRESS}:{VLESS_SERVER_PORT}?"
        f"type=ws&security=tls&path={VLESS_WS_PATH}&host={VLESS_SERVER_ADDRESS}"
        f"#{VLESS_REMARKS}"
    )


@app.post("/get_or_create_key")
async def get_or_create_key(user_info: dict):
    telegram_id = user_info.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id is required")

    db = SessionLocal()
    try:
        existing_user = db.query(User).filter(User.telegram_id == telegram_id).first()

        if existing_user:
            log.info(f"Found existing user: {telegram_id}. Returning their key.")
            return {"key": get_vless_link(existing_user.xray_uuid), "is_new": False}

        log.info(f"Creating new user for telegram_id: {telegram_id}")
        new_uuid = str(uuid.uuid4())
        new_user = User(
            telegram_id=telegram_id,
            xray_uuid=new_uuid,
            full_name=user_info.get("full_name", "")
        )
        db.add(new_user)

        if not add_user_to_xray_config(user_id=new_uuid, email=f"user_{telegram_id}"):
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not update Xray config.")

        restarted = await restart_xray_container()
        if not restarted:
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not restart Xray container.")

        db.commit()
        log.info(f"Successfully created new user: {telegram_id}")
        return {"key": get_vless_link(new_uuid), "is_new": True}

    except SQLAlchemyError as e:
        db.rollback()
        log.error(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Database error occurred.")
    finally:
        db.close()


# ==========================================================
#                  ЧАСТЬ 3: КОД ТЕЛЕГРАМ-БОТА
# ==========================================================
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()


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
    await call.answer("Проверяю ваш доступ...", show_alert=False)

    user_data_for_api = {"telegram_id": user_id, "full_name": user_fullname}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=user_data_for_api) as response:
                log.info(f"Internal API request to {API_URL} returned status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    vless_key = data.get("key")
                    is_new = data.get("is_new")

                    if is_new:
                        message_text = "✅ Ваш новый ключ готов!"
                    else:
                        message_text = "✅ Ваш ключ найден в базе."

                    response_text = (
                        f"{message_text}\n\n"
                        "Скопируйте его целиком и добавьте в свой клиент:\n\n"
                        f"<code>{vless_key}</code>"
                    )
                    await call.message.answer(response_text)
                else:
                    error_text = await response.text()
                    log.error(f"API returned an error. Status: {response.status}, Body: {error_text}")
                    await call.message.answer("❌ Не удалось сгенерировать ключ. Сервер API вернул ошибку.")
        except aiohttp.ClientConnectorError:
            log.exception(f"Could not connect to the API server at {API_URL}.")
            await call.message.answer(
                "❌ Ошибка подключения к внутреннему серверу API.\nПожалуйста, сообщите администратору.")
        except Exception:
            log.exception(f"An unexpected error occurred while processing request from user {user_id}.")
            await call.message.answer("❌ Произошла непредвиденная ошибка. Попробуйте позже.")


# ==========================================================
#                  ЧАСТЬ 4: ЗАПУСК
# ==========================================================
async def run_bot():
    log.info("Starting bot polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Этот блок будет запущен командой `python main.py` из скрипта start.sh
    # Uvicorn будет запущен отдельно этим же скриптом.
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")