import aiosqlite
import asyncio

# Список VLESS ключей — добавь сюда реальные
VLESS_KEYS = [
    "vless://uuid1@host:port?security=reality#Example1",
    "vless://uuid2@host:port?security=reality#Example2",
    "vless://uuid3@host:port?security=reality#Example3"
]

async def add_keys():
    async with aiosqlite.connect("vless_keys.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL
            )
        """)
        await db.executemany("INSERT INTO keys (key) VALUES (?)", [(k,) for k in VLESS_KEYS])
        await db.commit()
        print("Ключи успешно добавлены в базу.")

if __name__ == "__main__":
    asyncio.run(add_keys())