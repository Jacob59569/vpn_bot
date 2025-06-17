import random
import aiosqlite

async def get_one_key():
    async with aiosqlite.connect("vless_keys.db") as db:
        async with db.execute("SELECT key FROM keys") as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return None
            return random.choice(rows)[0]