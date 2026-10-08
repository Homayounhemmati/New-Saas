from datetime import datetime, timedelta

from . import dates
from .config import TZ

HELP = """سلام! من ربات برنامه‌ریزی شمایم 🗓

➕ /add عنوان | زمان — افزودن کار
   مثال: <code>/add خرید نان | فردا 18:30</code>
   زمان‌ها: امروز، فردا، پس‌فردا، شنبه…، ۱۴۰۵/۰۸/۱۵ 14:00، ۲ ساعت دیگر
📋 /today — کارهای امروز
📆 /week — برنامه ۷ روز آینده
🗂 /all — همه کارهای باز
📊 /stats — آمار و پیشرفت هفته
⏰ /morning 07:30 — ساعت برنامه صبحگاهی
🌙 /evening 21:00 — ساعت مرور شبانه
"""


def day_bounds(day: datetime) -> tuple[int, int]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def task_line(t) -> str:
    mark = "✅" if t["done_ts"] else "▫️"
    when = f" — {datetime.fromtimestamp(t['due_ts'], TZ):%H:%M}" if t["due_ts"] else ""
    return f"{mark} <b>{t['id']}</b>. {_esc(t['title'])}{when}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def progress_bar(done: int, total: int, width: int = 10) -> str:
    if not total:
        return "░" * width + " ۰٪"
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled) + f" {round(100 * done / total)}٪"


def streak(done_timestamps: list[int], today: datetime) -> int:
    """تعداد روزهای متوالی (تا امروز/دیروز) که حداقل یک کار انجام شده."""
    days = {datetime.fromtimestamp(ts, TZ).date() for ts in done_timestamps}
    d = today.date()
    if d not in days:
        d -= timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n
