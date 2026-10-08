from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from . import handlers, scheduler
from .config import BOT_TOKEN, DB_PATH
from .db import DB


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده؛ فایل .env را بسازید (.env.example را ببینید).")
    handlers.db = DB(DB_PATH)
    await handlers.db.open()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)
    task = asyncio.create_task(scheduler.run(bot, handlers.db))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await handlers.db.close()


if __name__ == "__main__":
    asyncio.run(main())
