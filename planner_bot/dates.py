"""تبدیل متن فارسی (امروز، فردا ۱۸:۳۰، ۱۴۰۵/۰۸/۱۵ …) به زمان و نمایش تاریخ شمسی."""
import re
from datetime import datetime, timedelta

import jdatetime

from .config import TZ

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# datetime.weekday(): دوشنبه=0 … یکشنبه=6
WEEKDAYS = {
    "دوشنبه": 0, "سه شنبه": 1, "سه‌شنبه": 1, "چهارشنبه": 2,
    "پنجشنبه": 3, "پنج شنبه": 3, "پنج‌شنبه": 3, "جمعه": 4,
    "شنبه": 5, "یکشنبه": 6, "یک شنبه": 6, "یک‌شنبه": 6,
}
WEEKDAY_NAMES = {0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنج‌شنبه",
                 4: "جمعه", 5: "شنبه", 6: "یکشنبه"}
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def now() -> datetime:
    return datetime.now(TZ)


def normalize(text: str) -> str:
    return text.translate(_DIGITS).replace("ي", "ی").replace("ك", "ک").strip()


def _time_of(text: str):
    m = re.search(r"(?:ساعت\s*)?(\d{1,2})(?::(\d{2}))?", text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if "عصر" in text or "شب" in text or "بعدازظهر" in text:
        if h < 12:
            h += 12
    if h > 23 or mi > 59:
        return None
    return h, mi


def parse_when(text: str, base: datetime | None = None) -> datetime | None:
    """زمان را برمی‌گرداند یا None اگر قابل فهم نبود."""
    base = base or now()
    t = normalize(text)

    # نسبی: «۲ ساعت دیگر»، «۳۰ دقیقه بعد»
    m = re.search(r"(\d+)\s*(ساعت|دقیقه)\s*(دیگر|بعد)", t)
    if m:
        n = int(m.group(1))
        delta = timedelta(hours=n) if m.group(2) == "ساعت" else timedelta(minutes=n)
        return (base + delta).replace(second=0, microsecond=0)

    # تاریخ شمسی: ۱۴۰۵/۰۸/۱۵ یا ۰۸/۱۵
    day = None
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", t)
    m2 = re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?![\d:])", t)
    try:
        if m:
            g = jdatetime.date(int(m[1]), int(m[2]), int(m[3])).togregorian()
            day, t = g, t.replace(m[0], " ")
        elif m2:
            jy = jdatetime.date.fromgregorian(date=base.date()).year
            g = jdatetime.date(jy, int(m2[1]), int(m2[2])).togregorian()
            day, t = g, t.replace(m2[0], " ")
    except ValueError:
        return None

    if day is None:
        if "پس‌فردا" in t or "پس فردا" in t:
            day = (base + timedelta(days=2)).date()
        elif "فردا" in t:
            day = (base + timedelta(days=1)).date()
        elif "امروز" in t or "امشب" in t:
            day = base.date()
        else:
            for name in sorted(WEEKDAYS, key=len, reverse=True):
                if name in t:
                    ahead = (WEEKDAYS[name] - base.weekday()) % 7 or 7
                    day = (base + timedelta(days=ahead)).date()
                    break

    tm = _time_of(t)
    if day is None and tm is None:
        return None
    if day is None:  # فقط ساعت داده شده: امروز، یا فردا اگر گذشته
        day = base.date()
        cand = datetime(day.year, day.month, day.day, *tm, tzinfo=TZ)
        return cand if cand > base else cand + timedelta(days=1)
    h, mi = tm or (9, 0)
    return datetime(day.year, day.month, day.day, h, mi, tzinfo=TZ)


def fmt_date(dt: datetime) -> str:
    j = jdatetime.datetime.fromgregorian(datetime=dt.astimezone(TZ))
    return f"{WEEKDAY_NAMES[dt.astimezone(TZ).weekday()]} {j.day} {MONTHS[j.month - 1]}"


def fmt_dt(ts: int | None) -> str:
    if ts is None:
        return "بدون زمان"
    dt = datetime.fromtimestamp(ts, TZ)
    return f"{fmt_date(dt)} · {dt:%H:%M}"
