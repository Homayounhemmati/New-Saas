from __future__ import annotations

import io
import re
import time
from datetime import timedelta

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import common, ctx, dates, mdplan, notify, texts
from .db import DEFAULT_CATEGORY, PERSONAL
from .keyboards import MAIN_MENU, list_kb, task_kb
from .taskparse import clean_category, parse_inline

router = Router()


class TouchUser(BaseMiddleware):
    """هر تعاملی کاربر (نام، یوزرنیم، فضای شخصی) را در دیتابیس به‌روز می‌کند."""

    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and not u.is_bot:
            await ctx.db.ensure_user(u.id, u.full_name or "", u.username)
        return await handler(event, data)


class AddTask(StatesGroup):
    title = State()
    when = State()


class ImportPlan(StatesGroup):
    wait = State()
    confirm = State()


MAX_IMPORT_BYTES = 200_000


@router.message(Command("cancel"))
async def cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("لغو شد.")


@router.message(CommandStart())
async def start(msg: Message):
    await msg.answer(texts.HELP, parse_mode="HTML", reply_markup=MAIN_MENU)


@router.message(Command("help"))
async def help_(msg: Message):
    await msg.answer(texts.HELP, parse_mode="HTML")


# ---------- افزودن کار ----------
async def create_task(msg: Message, text: str, when_text: str | None) -> bool:
    """True یعنی گفتگو تمام شد (موفق یا خطای غیرقابل‌اصلاح)؛ False یعنی دوباره زمان بپرس."""
    db, uid = ctx.db, msg.from_user.id
    inl = parse_inline(text)
    if not inl.title:
        await msg.answer("عنوان کار خالی است.")
        return True
    due = None
    if when_text and when_text.strip() not in ("-", "ندارد"):
        dt = dates.parse_when(when_text)
        if dt is None:
            await msg.answer("زمان را نفهمیدم 🤔 مثل «فردا 18:30» یا «۱۴۰۵/۰۸/۱۵ 14:00» بنویسید، "
                             "یا «-» برای بدون زمان.")
            return False
        due = int(dt.timestamp())
    if inl.recur and due is None:
        await msg.answer("برای کار تکرارشونده زمان لازم است (مثلاً «| فردا 7:00»).")
        return True
    ws = await db.active_ws(uid)
    assignee, unknown = await common.resolve_assignee(ws, uid, inl.mentions)
    if unknown:
        await msg.answer(f"عضو «{texts._esc(unknown)}» در «{texts._esc(ws['name'])}» پیدا نشد. /members")
        return True
    tid = await db.add_task(uid, ws["id"], inl.title, due, inl.category or DEFAULT_CATEGORY,
                            assignee, inl.priority, inl.est_min, inl.recur)
    t = await db.get_task(uid, tid)
    await msg.answer("ثبت شد ✔️\n" + texts.card_text(t), parse_mode="HTML",
                     reply_markup=task_kb(tid, team=ws["kind"] != PERSONAL))
    await common.announce_assignment(msg.bot, tid, msg.from_user, assignee)
    return True


@router.message(Command("add"))
async def add_cmd(msg: Message, command: CommandObject, state: FSMContext):
    if command.args:
        title, _, when = command.args.partition("|")
        if title.strip():
            await create_task(msg, title.strip(), when or None)
            return
    await state.set_state(AddTask.title)
    await msg.answer("عنوان کار چیست؟ (می‌توانید #دسته !فوری ~2h @عضو هم بنویسید)")


@router.message(F.text == "➕ کار جدید")
async def add_btn(msg: Message, state: FSMContext):
    await state.set_state(AddTask.title)
    await msg.answer("عنوان کار چیست؟ (می‌توانید #دسته !فوری ~2h @عضو هم بنویسید)")


@router.message(AddTask.title, F.text, ~F.text.startswith("/"))
async def add_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text.strip())
    await state.set_state(AddTask.when)
    await msg.answer("چه زمانی؟ (مثلاً «فردا 18:30»، «۲ ساعت دیگر»، یا «-» برای بدون زمان)")


@router.message(AddTask.when, F.text, ~F.text.startswith("/"))
async def add_when(msg: Message, state: FSMContext):
    title = (await state.get_data())["title"]
    if await create_task(msg, title, msg.text):
        await state.clear()


# ---------- برنامه من ----------
def _scope(cat, ws_id, ws_names: dict) -> str:
    if cat:
        return f" · 🏷 {texts._esc(cat)}"
    if ws_id:
        return f" · 🏢 {texts._esc(ws_names.get(ws_id, ''))}"
    return ""


async def _scope_for(uid, command):
    cat, ws_id = await common.filter_arg(uid, command)
    names = {w["id"]: w["name"] for w in await ctx.db.my_workspaces(uid)}
    return cat, ws_id, _scope(cat, ws_id, names)


async def _send_list(msg: Message, header: str, tasks, **kw):
    if not tasks:
        await msg.answer(f"{header}\nچیزی نیست 🎉", parse_mode="HTML")
        return
    foot = texts.workload(tasks)
    await common.send_long(msg, header + "\n" + "\n".join(texts.task_line(t) for t in tasks)
                           + (f"\n\n{foot}" if foot else ""), reply_markup=list_kb(tasks))


@router.message(Command("today"))
@router.message(F.text == "📋 امروز")
async def today(msg: Message, command: CommandObject | None = None):
    uid = msg.from_user.id
    cat, ws_id, scope = await _scope_for(uid, command)
    now = dates.now()
    s, e = texts.day_bounds(now)
    overdue = await ctx.db.overdue(uid, s, cat, ws_id)
    todays = await ctx.db.tasks_between(uid, s, e, cat, ws_id)
    await _send_list(msg, f"📋 <b>امروز — {dates.fmt_date(now)}</b>{scope}", todays)
    if overdue:
        await common.send_long(msg, "⚠️ عقب‌افتاده:\n" + "\n".join(texts.task_line(t) for t in overdue),
                               reply_markup=list_kb(overdue))


@router.message(Command("week"))
@router.message(F.text == "📆 هفته")
async def week(msg: Message, command: CommandObject | None = None):
    uid = msg.from_user.id
    cat, ws_id, scope = await _scope_for(uid, command)
    now = dates.now()
    lines = []
    for i in range(7):
        day = now + timedelta(days=i)
        s, e = texts.day_bounds(day)
        ts = await ctx.db.tasks_between(uid, s, e, cat, ws_id)
        lines.append(f"\n<b>{dates.fmt_date(day)}</b>")
        lines += [texts.task_line(t) for t in ts] or ["— آزاد —"]
    await common.send_long(msg, f"📆 <b>برنامه ۷ روز آینده</b>{scope}" + "\n".join(lines))


@router.message(Command("all"))
@router.message(Command("my"))
async def all_(msg: Message, command: CommandObject | None = None):
    uid = msg.from_user.id
    cat, ws_id, scope = await _scope_for(uid, command)
    await _send_list(msg, f"🗂 <b>همه کارهای باز من</b>{scope}", await ctx.db.open_tasks(uid, cat, ws_id))


@router.message(Command("cats"))
async def cats(msg: Message):
    rows = await ctx.db.categories(msg.from_user.id)
    if not rows:
        await msg.answer("هنوز دسته‌ای ندارید. با <code>/add عنوان #دسته</code> بسازید.",
                         parse_mode="HTML")
        return
    await msg.answer("🏷 <b>دسته‌ها</b>\n" + "\n".join(
        f"{r['emoji']} {texts._esc(r['name'])} — {r['open_count']} کار باز" for r in rows),
        parse_mode="HTML")


@router.message(Command("cat"))
async def cat_cmd(msg: Message, command: CommandObject):
    parts = (command.args or "").split()
    if not parts:
        await msg.answer("فرمت: <code>/cat ورزش 💪</code>", parse_mode="HTML")
        return
    emoji = parts[-1] if len(parts) > 1 and not parts[-1].isalnum() else None
    name = clean_category(" ".join(parts[:-1] if emoji else parts).lstrip("#"))
    await ctx.db.set_category(msg.from_user.id, name, emoji)
    await msg.answer(f"دسته «{texts._esc(name)}» {emoji or ''} آماده است ✔️")


@router.message(Command("stats"))
@router.message(F.text == "📊 آمار")
async def stats(msg: Message):
    db, uid = ctx.db, msg.from_user.id
    now = dates.now()
    s_today, e_today = texts.day_bounds(now)
    s_week = texts.day_bounds(now - timedelta(days=6))[0]
    td, tdd = await db.stats(uid, s_today, e_today)
    tw, twd = await db.stats(uid, s_week, e_today)
    st = texts.streak(await db.done_days(uid), now)
    emoji = {r["name"]: r["emoji"] for r in await db.categories(uid)}
    by_cat = "\n".join(
        f"{emoji.get(r['category'], '📌')} {texts._esc(r['category'])}: "
        f"{r['done']}/{r['total']}  {texts.progress_bar(r['done'], r['total'])}"
        for r in await db.stats_by_category(uid, s_week, e_today))
    await msg.answer(
        "📊 <b>آمار شما</b>\n"
        f"امروز: {tdd}/{td}\n{texts.progress_bar(tdd, td)}\n\n"
        f"۷ روز اخیر: {twd}/{tw}\n{texts.progress_bar(twd, tw)}\n\n"
        + (f"<b>به تفکیک دسته</b>\n{by_cat}\n\n" if by_cat else "")
        + f"🔥 روزهای متوالی فعال: {st}", parse_mode="HTML")


def _set_time_cmd(field: str, label: str):
    @router.message(Command(field))
    async def handler(msg: Message, command: CommandObject):
        arg = dates.normalize(command.args or "")
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", arg)
        if not m:
            await msg.answer(f"فرمت: /{field} 07:30")
            return
        await ctx.db.set_time(msg.from_user.id, field, f"{int(m[1]):02d}:{m[2]}")
        await msg.answer(f"ساعت {label} روی {int(m[1]):02d}:{m[2]} تنظیم شد ✔️")
    return handler


_set_time_cmd("morning", "برنامه صبحگاهی")
_set_time_cmd("evening", "مرور شبانه")


# ---------- ورود برنامه مارک‌داون ----------
IMPORT_PROMPT = ("برنامه هفته را به‌صورت متن مارک‌داون بفرستید (یا فایل .md/.txt آپلود کنید).\n\n"
                 "<pre>## شنبه\n- [ ] 07:00 ورزش #ورزش !مهم\n- 09:00 کار عمیق #کار ~2h\n"
                 "## یکشنبه\n- 18:30 جلسه تیم #کار @ali</pre>\n"
                 "عنوان‌ها = روز، #هشتگ = دسته، ساعت اختیاری است. /cancel برای انصراف.")


@router.message(Command("import"))
async def import_cmd(msg: Message, command: CommandObject, state: FSMContext):
    if command.args:
        await _preview(msg, state, command.args)
        return
    await state.set_state(ImportPlan.wait)
    await msg.answer(IMPORT_PROMPT, parse_mode="HTML")


@router.message(ImportPlan.wait, F.document)
async def import_file(msg: Message, state: FSMContext):
    doc = msg.document
    if (doc.file_size or 0) > MAX_IMPORT_BYTES:
        await msg.answer("فایل خیلی بزرگ است (حداکثر ۲۰۰ کیلوبایت).")
        return
    buf = io.BytesIO()
    await msg.bot.download(doc, destination=buf)
    try:
        text = buf.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        await msg.answer("فایل باید متنی با کدگذاری UTF-8 باشد.")
        return
    await _preview(msg, state, text)


@router.message(ImportPlan.wait, F.text, ~F.text.startswith("/"))
async def import_text(msg: Message, state: FSMContext):
    await _preview(msg, state, msg.text)


async def _preview(msg: Message, state: FSMContext, text: str):
    uid = msg.from_user.id
    items = mdplan.parse(text)
    if not items:
        await msg.answer("هیچ کاری پیدا نکردم 🤔 آیتم‌ها باید با «- » شروع شوند. /import را دوباره بزنید.")
        await state.clear()
        return
    ws = await ctx.db.active_ws(uid)
    rows, unknown = [], set()
    for i in items:
        assignee, bad = await common.resolve_assignee(ws, uid, i.mentions)
        if bad:
            unknown.add(bad)
        rows.append({"title": i.title, "category": i.category, "has_time": i.has_time,
                     "done": i.done, "priority": i.priority, "est_min": i.est_min,
                     "recur": i.recur if i.due else None, "assignee_id": assignee,
                     "due_ts": int(i.due.timestamp()) if i.due else None})
    await state.set_state(ImportPlan.confirm)
    await state.update_data(items=rows, ws_id=ws["id"])
    undated = sum(1 for i in items if i.due is None)
    shown = []
    for i in items[:40]:
        when = dates.fmt_dt(int(i.due.timestamp())) if i.due else "بدون زمان"
        if i.due and not i.has_time:
            when = dates.fmt_date(i.due)
        shown.append(f"{'✅' if i.done else '▫️'}{texts.PRIORITY_ICON[i.priority]} {texts._esc(i.title)}"
                     f" — {when} · #" + texts._esc(i.category.replace(" ", "_")))
    more = f"\n… و {len(items) - 40} مورد دیگر" if len(items) > 40 else ""
    warn = (f"\n\n⚠️ عضو ناشناخته: {', '.join(texts._esc(u) for u in unknown)} (به شما اساین می‌شود)"
            if unknown else "")
    await common.send_long(
        msg, f"📥 <b>{len(items)} کار پیدا شد</b> → {texts._esc(ws['name'])}"
        + (f" ({undated} تا بدون زمان)" if undated else "") + "\n\n" + "\n".join(shown) + more + warn)
    await msg.answer("ثبت شود؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ ثبت همه", callback_data="imp:ok"),
        InlineKeyboardButton(text="❌ لغو", callback_data="imp:no")]]))


@router.callback_query(ImportPlan.confirm, F.data == "imp:ok")
async def import_ok(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    db, uid, now_ts = ctx.db, cb.from_user.id, int(time.time())
    ws_id = data.get("ws_id")
    if not await db.member_role(ws_id, uid):
        await cb.answer("دسترسی ندارید")
        return
    added = skipped = 0
    for i in data.get("items", []):
        if await db.exists(ws_id, i["assignee_id"], i["title"], i["due_ts"]):
            skipped += 1
            continue
        notify_flag = bool(i["has_time"] and i["due_ts"] and i["due_ts"] > now_ts and not i["done"])
        tid = await db.add_task(uid, ws_id, i["title"], i["due_ts"], i["category"], i["assignee_id"],
                                i["priority"], i["est_min"], i["recur"], notify_flag)
        if i["done"]:
            await db.complete(uid, tid)
        added += 1
        if i["assignee_id"] and i["assignee_id"] != uid:
            await notify.send(cb.bot, i["assignee_id"],
                              f"📌 کار جدید از طرف {common.actor_name(cb.from_user)}: "
                              f"{texts._esc(i['title'])}")
    await cb.answer("ثبت شد")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        f"✔️ {added} کار ثبت شد" + (f" ({skipped} مورد تکراری رد شد)" if skipped else "")
        + "\nبرای دیدن: /week")


@router.callback_query(ImportPlan.confirm, F.data == "imp:no")
async def import_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("لغو شد")
    await cb.message.edit_reply_markup(reply_markup=None)


def setup(dp):
    """روترها و میدلور را به Dispatcher وصل می‌کند (ترتیب مهم است: تیم قبل از عمومی)."""
    from . import team
    dp.message.outer_middleware(TouchUser())
    dp.callback_query.outer_middleware(TouchUser())
    dp.include_router(team.router)
    dp.include_router(router)
