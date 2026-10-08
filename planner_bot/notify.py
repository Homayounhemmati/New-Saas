"""تنها نقطه ارسال اعلان به کاربران. اگر روزی کانال دیگری (ایمیل، …) اضافه شود فقط اینجا عوض می‌شود."""
from __future__ import annotations

import logging

from aiogram import Bot

log = logging.getLogger(__name__)


async def send(bot: Bot, user_id: int | None, text: str, reply_markup=None,
               exclude: int | None = None) -> bool:
    """پیام HTML به کاربر می‌فرستد؛ اگر خودِ عامل باشد (exclude) یا خطا بدهد، بی‌صدا رد می‌شود."""
    if not user_id or user_id == exclude:
        return False
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=reply_markup)
        return True
    except Exception:
        log.warning("notify failed for %s", user_id, exc_info=True)
        return False
