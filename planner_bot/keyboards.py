from __future__ import annotations

from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="➕ کار جدید"), KeyboardButton(text="📋 امروز")],
              [KeyboardButton(text="📆 هفته"), KeyboardButton(text="📊 آمار")],
              [KeyboardButton(text="🗂 برد"), KeyboardButton(text="🏢 فضاها")]],
    resize_keyboard=True)


def task_kb(task_id: int, snooze: bool = False, team: bool = False) -> InlineKeyboardMarkup:
    rows = [[B(text="✅ انجام شد", callback_data=f"done:{task_id}")]]
    if snooze:
        rows[0].append(B(text="⏰ ۱۰ دقیقه بعد", callback_data=f"snooze:{task_id}"))
    second = [B(text="▶️ شروع", callback_data=f"start:{task_id}"),
              B(text="➡️ لیست بعد", callback_data=f"next:{task_id}")]
    if team:
        second.append(B(text="👥 پاس", callback_data=f"pass:{task_id}"))
    rows.append(second)
    rows.append([B(text="🔍 جزئیات", callback_data=f"card:{task_id}"),
                 B(text="🗑", callback_data=f"del:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def list_kb(tasks) -> InlineKeyboardMarkup | None:
    open_tasks = [t for t in tasks if not t["done_ts"]]
    if not open_tasks:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text=f"✅ {t['id']}", callback_data=f"done:{t['id']}") for t in open_tasks[i:i + 4]]
        for i in range(0, len(open_tasks), 4)])


def members_kb(task_id: int, members, exclude: int | None = None) -> InlineKeyboardMarkup:
    btns = [B(text=m["name"] or f"@{m['username']}", callback_data=f"passto:{task_id}:{m['user_id']}")
            for m in members if m["user_id"] != exclude]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([B(text="🚫 بدون مسئول", callback_data=f"passto:{task_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def workspaces_kb(workspaces, active_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text=("● " if w["id"] == active_id else "") + ("🔒 " if w["kind"] == "personal" else "🏢 ")
           + w["name"], callback_data=f"ws:{w['id']}")] for w in workspaces])
