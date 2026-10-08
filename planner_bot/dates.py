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


def _find_day(t: str, base: datetime, today_ok: bool = False, short: bool = True):
    """روز را در متن پیدا می‌کند: (تاریخ یا None، متن بدون عبارت روز). ممکن است ValueError بدهد."""
    jy = jdatetime.date.fromgregorian(date=base.date()).year
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", t)
    if m:
        return jdatetime.date(int(m[1]), int(m[2]), int(m[3])).togregorian(), t.replace(m[0], " ")
    m = re.search(r"(?<!\d)(\d{1,2})\s*(%s)(?![\u0600-\u06FF])" % "|".join(MONTHS), t)
    if m:
        d = jdatetime.date(jy, MONTHS.index(m[2]) + 1, int(m[1])).togregorian()
        return d, t.replace(m[0], " ")
    if short:
        m = re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?![\d:])", t)
        if m:
            return jdatetime.date(jy, int(m[1]), int(m[2])).togregorian(), t.replace(m[0], " ")
    for token, ahead in (("پس‌فردا", 2), ("پس فردا", 2), ("فردا", 1), ("امروز", 0), ("امشب", 0)):
        if token in t:
            return (base + timedelta(days=ahead)).date(), t.replace(token, " ")
    for name in sorted(WEEKDAYS, key=len, reverse=True):
        if name in t:
            ahead = (WEEKDAYS[name] - base.weekday()) % 7
            if ahead == 0 and not today_ok:
                ahead = 7
            return (base + timedelta(days=ahead)).date(), t.replace(name, " ")
    return None, t


def find_day(text: str, base: datetime | None = None, today_ok: bool = False, short: bool = True):
    """نسخه امن _find_day؛ برای تاریخ نامعتبر (None، متن) برمی‌گرداند."""
    base = base or now()
    text = normalize(text)
    try:
        return _find_day(text, base, today_ok, short)
    except ValueError:
        return None, text


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

    try:
        day, t = _find_day(t, base)
    except ValueError:
        return None

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
