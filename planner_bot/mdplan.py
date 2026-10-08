"""تبدیل برنامه هفتگی نوشته‌شده به مارک‌داون به فهرست کار.

قواعد (انعطاف‌پذیر):
- عنوان‌هایی که روز هستند (شنبه، فردا، ۱۴۰۵/۰۷/۲۵، ۲۵ مهر) روز آیتم‌های زیرشان را تعیین می‌کنند.
- سایر عنوان‌ها (سطح ۲ به بعد) دسته‌اند؛ عنوان سطح ۱ فقط تیتر سند است.
- هر آیتم «- » یا «- [ ] » یک کار است؛ «#هشتگ» دسته، «۰۹:۰۰» ساعت، و [x] یعنی انجام‌شده.
- روز می‌تواند داخل خود آیتم هم بیاید: «- شنبه 09:00 جلسه».
- آیتم بدون روز، بدون موعد ثبت می‌شود.
"""
import re
from dataclasses import dataclass
from datetime import datetime

from . import dates
from .config import TZ
from .db import DEFAULT_CATEGORY

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[([ xX])\]\s*)?(.+?)\s*$")
_TAG = re.compile(r"#([^\s#]+)")
_TIME = re.compile(
    r"(?<![\d/])(?:ساعت\s*(\d{1,2})(?::([0-5]\d))?|(\d{1,2}):([0-5]\d))"
    r"(?:\s*[-–—]\s*\d{1,2}:[0-5]\d)?")
DEFAULT_HOUR = 9


@dataclass
class PlanItem:
    title: str
    category: str = DEFAULT_CATEGORY
    due: datetime | None = None
    has_time: bool = False
    done: bool = False


def clean_category(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.replace("_", " ").replace("‌", " ").strip(" :：-–—")).strip() \
        or DEFAULT_CATEGORY


def _heading_day(text: str, level: int, base: datetime):
    day, rest = dates.find_day(text, base, today_ok=True)
    if day is None:
        return None
    if level == 1 and re.sub(r"[\W\d_]+", "", rest):  # «# هفته ۱۶ مهر» تیتر سند است
        return None
    return day


def parse(text: str, base: datetime | None = None) -> list[PlanItem]:
    base = base or dates.now()
    day = None
    cat = None
    day_level = cat_level = None
    items: list[PlanItem] = []

    for line in dates.normalize(text.replace("\r", "")).split("\n"):
        h = _HEADING.match(line)
        if h:
            level, title = len(h[1]), h[2]
            d = _heading_day(title, level, base)
            if d is not None:
                day, day_level = d, level
                if cat_level is not None and level <= cat_level:
                    cat = cat_level = None
            elif level == 1:
                day = cat = day_level = cat_level = None
            else:
                cat, cat_level = clean_category(title), level
                if day_level is not None and level <= day_level:
                    day = day_level = None
            continue

        m = _ITEM.match(line)
        if not m:
            continue
        done = (m[1] or "").lower() == "x"
        body = m[2]

        tags = _TAG.findall(body)
        item_cat = clean_category(tags[0]) if tags else (cat or DEFAULT_CATEGORY)
        body = _TAG.sub(" ", body)

        item_day, body = dates.find_day(body, base, today_ok=True, short=False)
        the_day = item_day or day

        hour = minute = None
        t = _TIME.search(body)
        if t:
            hour = int(t[1] or t[3])
            minute = int(t[2] or t[4] or 0)
            if hour > 23:
                hour = minute = None
            else:
                if hour < 12 and re.search(r"عصر|شب|بعدازظهر", body):
                    hour += 12
                body = body.replace(t[0], " ")

        title = re.sub(r"\s+", " ", body).strip(" -–—:،,")
        if not title:
            continue

        due = None
        if the_day is not None:
            due = datetime(the_day.year, the_day.month, the_day.day,
                           hour if hour is not None else DEFAULT_HOUR,
                           minute if minute is not None else 0, tzinfo=TZ)
        items.append(PlanItem(title, item_cat, due, hour is not None, done))
    return items
