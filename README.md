# ربات تلگرامی برنامه‌ریزی

ربات فارسی با تقویم شمسی برای ثبت کار، یادآوری، برنامه روزانه/هفتگی و آمار پیشرفت.

## اجرا
```bash
pip install -r requirements.txt
cp .env.example .env   # BOT_TOKEN را از @BotFather بگذارید
python -m planner_bot.main
```

## دستورها
`/add عنوان | زمان` · `/today` · `/week` · `/all` · `/stats` · `/morning 07:30` · `/evening 21:00`

زمان‌ها: `امروز`، `فردا 18:30`، `شنبه 9`، `۱۴۰۵/۰۸/۱۵ 14:00`، `۲ ساعت دیگر`

## ساختار
- `dates.py` تحلیل زمان فارسی و نمایش شمسی
- `db.py` SQLite (aiosqlite)
- `handlers.py` دستورها و دکمه‌ها
- `scheduler.py` یادآوری‌ها، برنامه صبحگاهی و مرور شبانه

تست: `pytest`
