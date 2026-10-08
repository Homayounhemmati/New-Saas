from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from aiogram import Bot

from . import dates, notify, texts
from .db import DB, PERSONAL
from .keyboards import list_kb, task_kb

log = logging.getLogger(__name__)


async def send_reminders(bot: Bot, db: DB):
    for t in await db.due_unnotified(int(time.time())):
        await db.mark_notified(t["id"])
        await notify.send(bot, t["assignee_id"], f"⏰ <b>یادآوری</b>\n{texts.task_line(t)}",
                          task_kb(t["id"], snooze=True, team=t["ws_kind"] != PERSONAL))


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
            load = texts.workload(todays)
            body += f"\n\n{load}" if load else ""
            extra = (f"\n\n⚠️ عقب‌افتاده: {len(overdue)} کار (/today)" if overdue else "")
            await notify.send(bot, uid, f"🌅 <b>صبح بخیر! برنامه امروز — {dates.fmt_date(now)}</b>\n"
                             f"{body}{extra}", reply_markup=list_kb(todays))
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
            await notify.send(bot, uid, msg, reply_markup=list_kb(pending))


async def run(bot: Bot, db: DB, interval: int = 20):
    while True:
        try:
            await send_reminders(bot, db)
            await send_digests(bot, db)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
