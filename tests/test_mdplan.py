from datetime import datetime

from planner_bot import mdplan
from planner_bot.config import TZ

BASE = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)  # پنجشنبه ۱۴۰۵/۰۷/۱۶

MD = """# هفته ۱۶ مهر
## شنبه
- [ ] 07:00 ورزش #ورزش
- [x] 09:00-11:00 کار عمیق #کار
- مطالعه فصل 2-3
## ۲۵ مهر
- 10:00 قرار دکتر #شخصی
## کار
- یکشنبه 14:30 جلسه تیم
- گزارش
"""


def test_markdown_plan():
    items = {i.title: i for i in mdplan.parse(MD, BASE)}
    assert items["ورزش"].due == datetime(2026, 10, 10, 7, 0, tzinfo=TZ)
    assert items["ورزش"].category == "ورزش" and items["ورزش"].has_time
    assert items["کار عمیق"].done
    assert not items["مطالعه فصل 2-3"].has_time          # «2-3» تاریخ نیست
    assert items["قرار دکتر"].due == datetime(2026, 10, 17, 10, 0, tzinfo=TZ)
    assert items["جلسه تیم"].category == "کار"
    assert items["جلسه تیم"].due == datetime(2026, 10, 11, 14, 30, tzinfo=TZ)
    assert items["گزارش"].due is None


def test_nesting_and_empty():
    md = "## شنبه\n### کار\n- الف\n## یکشنبه\n- ب\n"
    a, b = mdplan.parse(md, BASE)
    assert a.category == "کار" and b.category == "عمومی"      # دسته با روز جدید ریست می‌شود
    assert mdplan.parse("متن بدون آیتم", BASE) == []
