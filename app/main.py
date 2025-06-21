import os
import asyncio
import logging
import json
import uuid
import random
import string
from datetime import datetime

# --- Импорты ---
from fastapi import FastAPI, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from aiogram.client.default import DefaultBotProperties
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
import aiohttp

# ==========================================================
#                  КОНФИГУРАЦИЯ
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000/get_or_create_key"
XRAY_CONFIG_PATH = "/app/config.json"
XRAY_CONTAINER_NAME = "vpn_xray"
DATABASE_PATH = "/app/data/users.db"

# --- НАСТРОЙКИ ДЛЯ REALITY (ЗАМЕНИТЕ НА СВОИ!) ---
REALITY_SERVER_ADDRESS = "shieldvpn.ru"
REALITY_SERVER_PORT = 443
REALITY_PUBLIC_KEY = "8PSiSpiSdXQLCGVXszWueRRsqflMboBXBFAx7MDLTjo"  # <-- ВСТАВЬТЕ СГЕНЕРИРОВАННЫЙ PUBLIC KEY
REALITY_SERVER_NAME = "yahoo.com"
REALITY_REMARKS = "ShieldVPN-Reality"

# ==========================================================
#                  БАЗА ДАННЫХ
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


os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
Base.metadata.create_all(bind=engine)

# ==========================================================
#                  ЛОГИКА API и VLESS-REALITY
# ==========================================================
app = FastAPI()


async def restart_xray_container():
    """Перезапускает сервис Xray через docker-compose."""
    # Мы находимся в контейнере, который является частью docker-compose проекта.
    # Мы можем выполнить команду docker-compose restart для другого сервиса.
    # Указываем путь к нашему compose-файлу, который мы можем найти по WORKDIR
    command = "docker-compose -f /app/docker-compose.yml restart xray"
    log.info(f"Executing command: {command}")
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            log.info(f"Service 'xray' restarted successfully. Output: {stdout.decode().strip()}")
            return True
        else:
            log.error(f"Failed to restart service 'xray'. Exit code: {process.returncode}. Error: {stderr.decode().strip()}")
            return False
    except Exception as e:
        log.error(f"Exception while trying to restart service 'xray': {e}")
        return False


def add_user_to_xray_config(user_id: str, short_id: str, email: str) -> bool:
    """Добавляет нового пользователя И ЕГО SHORT_ID в JSON-конфигурацию Xray."""
    try:
        with open(XRAY_CONFIG_PATH, 'r+') as f:
            config = json.load(f)
            inbound_settings = config['inbounds'][0]['settings']
            reality_settings = config['inbounds'][0]['streamSettings']['realitySettings']

            # Добавляем нового клиента
            new_client = {"id": user_id, "email": email}
            inbound_settings.setdefault('clients', []).append(new_client)

            # Добавляем новый shortId
            reality_settings.setdefault('shortIds', []).append(short_id)

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
            log.info(f"Successfully added user {email} ({user_id}) with shortId {short_id} to config.")
            return True
    except Exception as e:
        log.error(f"Failed to update Xray config: {e}")
        return False


def get_vless_reality_link(user_uuid: str, short_id: str) -> str:
    """Формирует VLESS-ссылку для протокола REALITY."""
    return (
        f"vless://{user_uuid}@{REALITY_SERVER_ADDRESS}:{REALITY_SERVER_PORT}?"
        f"security=reality&encryption=none&pbk={REALITY_PUBLIC_KEY}"
        f"&headerType=none&type=tcp&sni={REALITY_SERVER_NAME}&sid={short_id}"
        f"#{REALITY_REMARKS}"
    )


@app.post("/get_or_create_key")
async def get_or_create_key(user_info: dict):
    telegram_id = user_info.get("telegram_id")
    if not telegram_id: raise HTTPException(status_code=400, detail="telegram_id is required")

    db = SessionLocal()
    try:
        existing_user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if existing_user:
            log.info(f"Found existing user: {telegram_id}. Returning their key.")
            return {"key": get_vless_reality_link(existing_user.xray_uuid, existing_user.short_id), "is_new": False}

        log.info(f"Creating new user for telegram_id: {telegram_id}")
        new_uuid = str(uuid.uuid4())
        new_short_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

        new_user = User(
            telegram_id=telegram_id,
            xray_uuid=new_uuid,
            short_id=new_short_id,  # Сохраняем short_id в БД
            full_name=user_info.get("full_name", "")
        )
        db.add(new_user)

        if not add_user_to_xray_config(user_id=new_uuid, short_id=new_short_id, email=f"user_{telegram_id}"):
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not update Xray config.")

        restarted = await restart_xray_container()
        if not restarted:
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not restart Xray container.")

        db.commit()
        log.info(f"Successfully created new user: {telegram_id}")
        return {"key": get_vless_reality_link(new_uuid, new_short_id), "is_new": True}
    finally:
        db.close()


# ==========================================================
#                  КОД ТЕЛЕГРАМ-БОТА (без изменений)
# ==========================================================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    kb = [[types.InlineKeyboardButton(text="🔑 Получить REALITY ключ", callback_data="get_vless_key")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("Привет! Нажми на кнопку, чтобы получить новый ключ доступа (VLESS + REALITY):",
                         reply_markup=keyboard)


@dp.callback_query(F.data == "get_vless_key")
async def get_vless_key_handler(call: types.CallbackQuery):
    await call.answer("Проверяю ваш доступ...", show_alert=False)
    user_data_for_api = {"telegram_id": call.from_user.id, "full_name": call.from_user.full_name}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=user_data_for_api) as response:
                if response.status == 200:
                    data = await response.json()
                    message_text = "✅ Ваш новый ключ готов!" if data.get("is_new") else "✅ Ваш ключ найден в базе."
                    response_text = (
                        f"{message_text}\n\n"
                        "Скопируйте его целиком и добавьте в свой клиент:\n\n"
                        f"<code>{data.get('key')}</code>"
                    )
                    await call.message.answer(response_text)
                else:
                    error_text = await response.text()
                    log.error(f"API returned an error. Status: {response.status}, Body: {error_text}")
                    await call.message.answer("❌ Не удалось сгенерировать ключ. Сервер API вернул ошибку.")
        except Exception as e:
            log.exception(f"An unexpected error occurred: {e}")
            await call.message.answer("❌ Произошла непредвиденная ошибка.")


# ==========================================================
#                  ЗАПУСК
# ==========================================================
async def run_bot():
    log.info("Starting bot polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped!")