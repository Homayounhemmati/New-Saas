import asyncio
import time
from datetime import datetime

from planner_bot import dates, texts
from planner_bot.config import TZ
from planner_bot.db import DB

BASE = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)  # پنجشنبه ۱۴۰۵/۰۷/۱۶


def test_relative_and_named_days():
    assert dates.parse_when("فردا 18:30", BASE) == datetime(2026, 10, 9, 18, 30, tzinfo=TZ)
    assert dates.parse_when("امروز ۱۸", BASE) == datetime(2026, 10, 8, 18, 0, tzinfo=TZ)
    assert dates.parse_when("۲ ساعت دیگر", BASE) == datetime(2026, 10, 8, 12, 0, tzinfo=TZ)
    assert dates.parse_when("شنبه 9:00", BASE) == datetime(2026, 10, 10, 9, 0, tzinfo=TZ)
    assert dates.parse_when("پس‌فردا", BASE) == datetime(2026, 10, 10, 9, 0, tzinfo=TZ)


def test_jalali_date_and_time_only():
    assert dates.parse_when("۱۴۰۵/۰۸/۱۵ 14:00", BASE) == datetime(2026, 11, 6, 14, 0, tzinfo=TZ)
    assert dates.parse_when("ساعت 8", BASE) == datetime(2026, 10, 9, 8, 0, tzinfo=TZ)
    assert dates.parse_when("هر چیزی", BASE) is None
    assert dates.parse_when("1405/13/40", BASE) is None


def test_progress_and_streak():
    assert texts.progress_bar(1, 2).endswith("50٪")
    now = int(BASE.timestamp())
    assert texts.streak([now, now - 86400, now - 2 * 86400, now - 5 * 86400], BASE) == 3
    assert texts.streak([], BASE) == 0


def test_db_flow(tmp_path):
    async def go():
        db = DB(str(tmp_path / "t.db"))
        await db.open()
        now = int(time.time())
        a = await db.add_task(1, "الف", now - 60)
        await db.add_task(2, "ب", now - 60)
        assert {t["id"] for t in await db.due_unnotified(now)} >= {a}
        assert not await db.complete(2, a)          # کاربر دیگر نمی‌تواند ببندد
        assert await db.complete(1, a)
        assert (await db.stats(1, now - 3600, now + 3600)) == (1, 1)
        await db.reschedule(1, a, now + 600)
        assert (await db.get_task(1, a))["notified"] == 0
        await db.close()
    asyncio.run(go())
