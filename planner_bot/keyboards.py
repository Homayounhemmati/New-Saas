from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="➕ کار جدید"), KeyboardButton(text="📋 امروز")],
              [KeyboardButton(text="📆 هفته"), KeyboardButton(text="📊 آمار")]],
    resize_keyboard=True)


def task_kb(task_id: int, snooze: bool = False) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="✅ انجام شد", callback_data=f"done:{task_id}")]
    if snooze:
        row.append(InlineKeyboardButton(text="⏰ ۱۰ دقیقه بعد", callback_data=f"snooze:{task_id}"))
    row.append(InlineKeyboardButton(text="🗑", callback_data=f"del:{task_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def list_kb(tasks) -> InlineKeyboardMarkup | None:
    open_tasks = [t for t in tasks if not t["done_ts"]]
    if not open_tasks:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ {t['id']}", callback_data=f"done:{t['id']}")
         for t in open_tasks[i:i + 4]] for i in range(0, len(open_tasks), 4)])
