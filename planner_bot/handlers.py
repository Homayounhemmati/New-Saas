import re
import time
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from . import dates, texts
from .config import DEFAULT_EVENING, DEFAULT_MORNING
from .db import DB
from .keyboards import MAIN_MENU, list_kb, task_kb

router = Router()
db: DB  # در main مقداردهی می‌شود


class AddTask(StatesGroup):
    title = State()
    when = State()


async def _ensure(msg: Message):
    await db.ensure_user(msg.from_user.id, DEFAULT_MORNING, DEFAULT_EVENING)


@router.message(CommandStart())
async def start(msg: Message):
    await _ensure(msg)
    await msg.answer(texts.HELP, parse_mode="HTML", reply_markup=MAIN_MENU)


@router.message(Command("help"))
async def help_(msg: Message):
    await msg.answer(texts.HELP, parse_mode="HTML")


async def _create(msg: Message, title: str, when_text: str | None):
    due = None
    if when_text and when_text.strip() not in ("-", "ندارد"):
        dt = dates.parse_when(when_text)
        if dt is None:
            await msg.answer("زمان را نفهمیدم 🤔 مثل «فردا 18:30» یا «۱۴۰۵/۰۸/۱۵ 14:00» بنویسید، "
                             "یا «-» برای بدون زمان.")
            return False
        due = int(dt.timestamp())
    tid = await db.add_task(msg.from_user.id, title, due)
    await msg.answer(f"ثبت شد ✔️\n▫️ <b>{tid}</b>. {texts._esc(title)}\n🕒 {dates.fmt_dt(due)}",
                     parse_mode="HTML", reply_markup=task_kb(tid))
    return True


@router.message(Command("add"))
async def add_cmd(msg: Message, command: CommandObject, state: FSMContext):
    await _ensure(msg)
    if command.args:
        title, _, when = command.args.partition("|")
        if title.strip():
            await _create(msg, title.strip(), when or None)
            return
    await state.set_state(AddTask.title)
    await msg.answer("عنوان کار چیست؟")


@router.message(F.text == "➕ کار جدید")
async def add_btn(msg: Message, state: FSMContext):
    await _ensure(msg)
    await state.set_state(AddTask.title)
    await msg.answer("عنوان کار چیست؟")


@router.message(AddTask.title, F.text)
async def add_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text.strip())
    await state.set_state(AddTask.when)
    await msg.answer("چه زمانی؟ (مثلاً «فردا 18:30»، «۲ ساعت دیگر»، یا «-» برای بدون زمان)")


@router.message(AddTask.when, F.text)
async def add_when(msg: Message, state: FSMContext):
    title = (await state.get_data())["title"]
    if await _create(msg, title, msg.text):
        await state.clear()


async def _send_list(msg: Message, header: str, tasks):
    if not tasks:
        await msg.answer(f"{header}\nچیزی نیست 🎉")
        return
    await msg.answer(header + "\n" + "\n".join(texts.task_line(t) for t in tasks),
                     parse_mode="HTML", reply_markup=list_kb(tasks))


@router.message(Command("today"))
@router.message(F.text == "📋 امروز")
async def today(msg: Message):
    await _ensure(msg)
    now = dates.now()
    s, e = texts.day_bounds(now)
    overdue = await db.overdue(msg.from_user.id, s)
    todays = await db.tasks_between(msg.from_user.id, s, e)
    header = f"📋 <b>امروز — {dates.fmt_date(now)}</b>"
    if overdue:
        header += "\n⚠️ عقب‌افتاده:\n" + "\n".join(texts.task_line(t) for t in overdue) + "\n\nامروز:"
    await _send_list(msg, header, todays)
    if overdue:
        await msg.answer("برای بستن عقب‌افتاده‌ها:", reply_markup=list_kb(overdue))


@router.message(Command("week"))
@router.message(F.text == "📆 هفته")
async def week(msg: Message):
    await _ensure(msg)
    now = dates.now()
    lines = []
    for i in range(7):
        day = now + timedelta(days=i)
        s, e = texts.day_bounds(day)
        ts = await db.tasks_between(msg.from_user.id, s, e)
        lines.append(f"\n<b>{dates.fmt_date(day)}</b>")
        lines += [texts.task_line(t) for t in ts] or ["— آزاد —"]
    await msg.answer("📆 <b>برنامه ۷ روز آینده</b>" + "\n".join(lines), parse_mode="HTML")


@router.message(Command("all"))
async def all_(msg: Message):
    await _ensure(msg)
    tasks = await db.open_tasks(msg.from_user.id)
    await _send_list(msg, "🗂 <b>همه کارهای باز</b>", tasks)


@router.message(Command("stats"))
@router.message(F.text == "📊 آمار")
async def stats(msg: Message):
    await _ensure(msg)
    now = dates.now()
    s_today, e_today = texts.day_bounds(now)
    s_week = texts.day_bounds(now - timedelta(days=6))[0]
    td, tdd = await db.stats(msg.from_user.id, s_today, e_today)
    tw, twd = await db.stats(msg.from_user.id, s_week, e_today)
    st = texts.streak(await db.done_days(msg.from_user.id), now)
    await msg.answer(
        "📊 <b>آمار شما</b>\n"
        f"امروز: {tdd}/{td}\n{texts.progress_bar(tdd, td)}\n\n"
        f"۷ روز اخیر: {twd}/{tw}\n{texts.progress_bar(twd, tw)}\n\n"
        f"🔥 روزهای متوالی فعال: {st}", parse_mode="HTML")


def _set_time_cmd(field: str, label: str):
    @router.message(Command(field))
    async def handler(msg: Message, command: CommandObject):
        await _ensure(msg)
        arg = dates.normalize(command.args or "")
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", arg)
        if not m:
            await msg.answer(f"فرمت: /{field} 07:30")
            return
        await db.set_time(msg.from_user.id, field, f"{int(m[1]):02d}:{m[2]}")
        await msg.answer(f"ساعت {label} روی {int(m[1]):02d}:{m[2]} تنظیم شد ✔️")
    return handler


_set_time_cmd("morning", "برنامه صبحگاهی")
_set_time_cmd("evening", "مرور شبانه")


@router.callback_query(F.data.startswith("done:"))
async def cb_done(cb: CallbackQuery):
    ok = await db.complete(cb.from_user.id, int(cb.data.split(":")[1]))
    await cb.answer("آفرین! ✅" if ok else "قبلاً انجام شده بود")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("snooze:"))
async def cb_snooze(cb: CallbackQuery):
    tid = int(cb.data.split(":")[1])
    await db.reschedule(cb.from_user.id, tid, int(time.time()) + 600)
    await cb.answer("۱۰ دقیقه دیگر یادآوری می‌کنم ⏰")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery):
    await db.delete(cb.from_user.id, int(cb.data.split(":")[1]))
    await cb.answer("حذف شد 🗑")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
