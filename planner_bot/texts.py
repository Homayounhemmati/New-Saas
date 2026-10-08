from __future__ import annotations

from datetime import datetime, timedelta

from . import dates
from .config import TZ

HELP = """سلام! من دستیار برنامه‌ریزی و مدیریت کار تیمی شما هستم 🗓

<b>افزودن کار</b>
<code>/add گزارش فروش #کار !فوری ~2h @ali *هفتگی | فردا 18:30</code>
#دسته · !فوری/!مهم/!عادی · ~تخمین (2h یا 30m) · @مسئول · *روزانه/هفتگی/ماهانه
زمان: امروز، فردا، شنبه…، ۱۴۰۵/۰۸/۱۵ 14:00، ۲ ساعت دیگر

<b>برنامه من</b>
📋 /today · 📆 /week · 🗂 /all (کارهای من در همه فضاها)
فیلتر: <code>/today ورزش</code> (دسته) یا <code>/week شرکت</code> (فضا)
📊 /stats · 🏷 /cats · /cat ورزش 💪
⏰ /morning 07:30 · 🌙 /evening 21:00 · 📥 /import (برنامه مارک‌داون)

<b>تیم و برد (مثل Trello)</b>
🏢 /ws — فضاها و جابه‌جایی بین آن‌ها
➕ /team نام — ساخت تیم · /invite — لینک دعوت · /members — اعضا
🗂 /board — برد فعال · /boards · /newboard نام
🔍 /card 12 — جزئیات کار؛ دکمه‌ها: انجام، لیست بعد، پاس‌دادن
✏️ /due 12 فردا 9 · /title 12 متن · /pri 12 فوری · /move 12 در حال انجام
👤 /pass 12 @ali · 💬 /note 12 متن · 🗑 /del 12
"""

PRIORITY_ICON = {1: "🔴", 2: "🟠", 3: ""}
PRIORITY_NAME = {1: "فوری", 2: "مهم", 3: "عادی"}


def day_bounds(day: datetime) -> tuple[int, int]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def person(name: str | None, username: str | None = None) -> str:
    return _esc(name or (f"@{username}" if username else "—")) if (name or username) else "—"


def fmt_est(minutes: int | None) -> str:
    if not minutes:
        return ""
    h, m = divmod(minutes, 60)
    return (f"{h}س" if h else "") + (f"{m}د" if m else "")


def task_line(t, show_ws: bool = True, show_assignee: bool = False) -> str:
    mark = "✅" if t["done_ts"] else "▫️"
    when = f" — {datetime.fromtimestamp(t['due_ts'], TZ):%H:%M}" if t["due_ts"] else ""
    pri = PRIORITY_ICON.get(t["priority"], "")
    est = f" ⏱{fmt_est(t['est_min'])}" if t["est_min"] else ""
    cat = "" if t["category"] == "عمومی" else f" #{_esc(t['category'].replace(' ', '_'))}"
    ws = f" 🏢{_esc(t['ws_name'])}" if show_ws and t["ws_kind"] == "team" else ""
    who = f" 👤{person(t['assignee_name'], t['assignee_username'])}" if show_assignee else ""
    rec = " 🔁" if t["recur"] else ""
    return f"{mark}{pri} <b>{t['id']}</b>. {_esc(t['title'])}{when}{est}{rec}{cat}{ws}{who}"


def card_text(t, comments=()) -> str:
    lines = [
        f"{PRIORITY_ICON.get(t['priority'], '')}<b>#{t['id']} · {_esc(t['title'])}</b>",
        f"🏢 {_esc(t['ws_name'])} › {_esc(t['list_name'] or '—')}",
        f"👤 مسئول: {person(t['assignee_name'], t['assignee_username'])}",
        f"🕒 {dates.fmt_dt(t['due_ts'])}",
        f"⚡️ اولویت: {PRIORITY_NAME[t['priority']]}"
        + (f" · ⏱ {fmt_est(t['est_min'])}" if t["est_min"] else "")
        + (f" · 🏷 {_esc(t['category'])}" if t["category"] != "عمومی" else "")
        + (f" · 🔁 {dict(daily='روزانه', weekly='هفتگی', monthly='ماهانه')[t['recur']]}"
           if t["recur"] else ""),
    ]
    if t["description"]:
        lines.append(f"\n{_esc(t['description'])}")
    if comments:
        lines.append("\n💬 <b>یادداشت‌ها</b>")
        lines += [f"• {_esc(c['name'] or '—')}: {_esc(c['text'])}" for c in reversed(list(comments))]
    return "\n".join(lines)


def progress_bar(done: int, total: int, width: int = 10) -> str:
    if not total:
        return "░" * width + " ۰٪"
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled) + f" {round(100 * done / total)}٪"


def workload(tasks) -> str:
    """مجموع زمان تخمینی کارهای باز، برای دستیار برنامه‌ریز."""
    total = sum(t["est_min"] or 0 for t in tasks if not t["done_ts"])
    unknown = sum(1 for t in tasks if not t["done_ts"] and not t["est_min"])
    if not total:
        return ""
    return f"⏱ حجم کار تخمینی: {fmt_est(total)}" + (f" (+{unknown} کار بدون تخمین)" if unknown else "")


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
