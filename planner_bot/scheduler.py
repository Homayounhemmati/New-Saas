from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from aiogram import Bot

from . import dates, texts
from .db import DB
from .keyboards import list_kb, task_kb

log = logging.getLogger(__name__)


async def _safe_send(bot: Bot, chat_id: int, *args, **kwargs):
    try:
        await bot.send_message(chat_id, *args, **kwargs)
        return True
    except Exception:  # کاربر ربات را بلاک کرده و …
        log.exception("send failed to %s", chat_id)
        return False


async def send_reminders(bot: Bot, db: DB):
    for t in await db.due_unnotified(int(time.time())):
        await db.mark_notified(t["id"])
        await _safe_send(bot, t["user_id"], f"⏰ <b>یادآوری</b>\n{texts.task_line(t)}",
                         parse_mode="HTML", reply_markup=task_kb(t["id"], snooze=True))


async def send_digests(bot: Bot, db: DB):
    now = dates.now()
    today_key = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    for u in await db.all_users():
        uid = u["user_id"]
        if hhmm >= u["morning"] and u["last_morning"] != today_key:
            await db.mark_digest(uid, "last_morning", today_key)
            s, e = texts.day_bounds(now)
            todays = await db.tasks_between(uid, s, e)
            overdue = await db.overdue(uid, s)
            body = "\n".join(texts.task_line(t) for t in todays) or "برنامه‌ای برای امروز ثبت نشده."
            extra = (f"\n\n⚠️ عقب‌افتاده: {len(overdue)} کار (/today)" if overdue else "")
            await _safe_send(bot, uid, f"🌅 <b>صبح بخیر! برنامه امروز — {dates.fmt_date(now)}</b>\n"
                             f"{body}{extra}", parse_mode="HTML", reply_markup=list_kb(todays))
        if hhmm >= u["evening"] and u["last_evening"] != today_key:
            await db.mark_digest(uid, "last_evening", today_key)
            s, e = texts.day_bounds(now)
            total, done = await db.stats(uid, s, e)
            pending = [t for t in await db.tasks_between(uid, s, e) if not t["done_ts"]]
            msg = f"🌙 <b>مرور امروز</b>\n{done}/{total}\n{texts.progress_bar(done, total)}"
            if pending:
                msg += ("\n\nنیمه‌کاره‌ها:\n" + "\n".join(texts.task_line(t) for t in pending)
                        + "\nبرای فردا جابجا کنید یا انجام‌شده بزنید.")
            else:
                msg += "\n\nعالی بود! همه‌چیز انجام شد 🎉" if total else ""
            await _safe_send(bot, uid, msg, parse_mode="HTML", reply_markup=list_kb(pending))


async def run(bot: Bot, db: DB, interval: int = 20):
    while True:
        try:
            await send_reminders(bot, db)
            await send_digests(bot, db)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
