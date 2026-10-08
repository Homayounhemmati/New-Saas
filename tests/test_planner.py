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
        await db.ensure_user(1, "الف", "alef")
        await db.ensure_user(2, "ب", "bee")
        now = int(time.time())
        w1, w2 = await db.personal_ws(1), await db.personal_ws(2)
        a = await db.add_task(1, w1, "الف", now - 60, assignee_id=1)
        await db.add_task(2, w2, "ب", now - 60, assignee_id=2)
        assert {t["id"] for t in await db.due_unnotified(now)} >= {a}
        assert not await db.complete(2, a)          # کاربر دیگر به فضای شخصی من دسترسی ندارد
        t, nxt = await db.complete(1, a)
        assert t["id"] == a and nxt is None
        assert (await db.stats(1, now - 3600, now + 3600)) == (1, 1)
        assert (await db.get_task(1, a))["list_name"].endswith("انجام شد")
        await db.update_task(1, a, due_ts=now + 600)
        assert (await db.get_task(1, a))["notified"] == 0
        await db.close()
    asyncio.run(go())


def test_recurring_next_due():
    from planner_bot.db import next_due
    ts = int(datetime(2026, 10, 8, 7, 0, tzinfo=TZ).timestamp())
    assert datetime.fromtimestamp(next_due(ts, "daily"), TZ).day == 9
    assert datetime.fromtimestamp(next_due(ts, "weekly"), TZ).day == 15
    nxt = datetime.fromtimestamp(next_due(ts, "monthly"), TZ)
    assert (nxt.month, nxt.day) == (11, 7)   # ۱۶ مهر ← ۱۶ آبان
