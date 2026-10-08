"""فضای کاری تیمی، برد کانبان و عملیات روی کارت‌ها (دستورها و دکمه‌ها)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from . import common, ctx, dates, notify, texts
from .common import actor_name
from .db import PERSONAL, TEAM
from .keyboards import members_kb, task_kb, workspaces_kb
from .taskparse import PRIORITY_WORDS

router = Router()
ROLE_NAMES = {"admin": "مدیر", "member": "عضو"}


async def _active(msg_or_cb):
    return await ctx.db.active_ws(msg_or_cb.from_user.id)


async def _require_team(msg: Message):
    ws = await _active(msg)
    if ws["kind"] != TEAM:
        await msg.answer("این دستور برای فضای تیمی است. با /team نام یک تیم بسازید یا با /ws به تیم بروید.")
        return None
    return ws


async def _require_admin(msg: Message):
    ws = await _require_team(msg)
    if ws and await ctx.db.member_role(ws["id"], msg.from_user.id) != "admin":
        await msg.answer("فقط مدیر تیم می‌تواند این کار را انجام دهد.")
        return None
    return ws


async def _link(bot, ws) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=join_{ws['invite_code']}"


# ---------- تیم و اعضا ----------
@router.message(Command("team"))
async def team_cmd(msg: Message, command: CommandObject):
    name = (command.args or "").strip()
    if not name:
        await msg.answer("فرمت: <code>/team نام تیم</code>", parse_mode="HTML")
        return
    ws_id = await ctx.db.create_team(msg.from_user.id, name[:40])
    ws = await ctx.db.get_ws(ws_id)
    await msg.answer(
        f"🏢 تیم «{texts._esc(ws['name'])}» ساخته شد و فضای فعال شما شد.\n\n"
        f"لینک دعوت اعضا (برای ارسال به آن‌ها):\n{await _link(msg.bot, ws)}\n\n"
        "هر کاری که حالا با /add اضافه کنید، روی برد «عمومی» همین تیم می‌نشیند. "
        "برای برد: /board", parse_mode="HTML")


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("join_")))
async def join_cmd(msg: Message, command: CommandObject):
    ws = await ctx.db.ws_by_invite((command.args or "")[5:])
    if not ws:
        await msg.answer("این لینک دعوت معتبر نیست یا منقضی شده.")
        return
    uid = msg.from_user.id
    fresh = await ctx.db.join(ws["id"], uid)
    await msg.answer(
        (f"✅ به تیم «{texts._esc(ws['name'])}» پیوستید." if fresh
         else f"شما قبلاً عضو «{texts._esc(ws['name'])}» هستید.")
        + "\nبرای کار روی برد تیم: /ws را بزنید و آن را فعال کنید. کارهایی که به شما اساین شود "
          "همین‌جا اعلان می‌شود. راهنما: /help", parse_mode="HTML")
    if fresh:
        for m in await ctx.db.members(ws["id"]):
            if m["role"] == "admin":
                await notify.send(msg.bot, m["user_id"],
                                  f"👋 {actor_name(msg.from_user)} به تیم «{texts._esc(ws['name'])}» پیوست.",
                                  exclude=uid)


@router.message(Command("invite"))
async def invite_cmd(msg: Message):
    ws = await _require_admin(msg)
    if ws:
        await msg.answer(f"🔗 لینک دعوت «{texts._esc(ws['name'])}»:\n{await _link(msg.bot, ws)}")


@router.message(Command("members"))
async def members_cmd(msg: Message):
    ws = await _require_team(msg)
    if not ws:
        return
    rows = await ctx.db.members(ws["id"])
    await msg.answer(f"👥 <b>اعضای {texts._esc(ws['name'])}</b>\n" + "\n".join(
        f"{'👑' if m['role'] == 'admin' else '•'} {texts._esc(m['name'] or '—')}"
        + (f" (@{m['username']})" if m["username"] else "") for m in rows), parse_mode="HTML")


@router.message(Command("ws"))
@router.message(F.text == "🏢 فضاها")
async def ws_cmd(msg: Message):
    uid = msg.from_user.id
    active = await _active(msg)
    await msg.answer("🏢 فضای فعال را انتخاب کنید (کارهای جدید و برد در آن قرار می‌گیرند):",
                     reply_markup=workspaces_kb(await ctx.db.my_workspaces(uid), active["id"]))


@router.callback_query(F.data.startswith("ws:"))
async def cb_ws(cb: CallbackQuery):
    ws_id = int(cb.data.split(":")[1])
    if not await ctx.db.set_active_ws(cb.from_user.id, ws_id):
        await cb.answer("دسترسی ندارید")
        return
    ws = await ctx.db.get_ws(ws_id)
    await cb.answer(f"فضای فعال: {ws['name']}")
    if cb.message:
        await cb.message.edit_reply_markup(
            reply_markup=workspaces_kb(await ctx.db.my_workspaces(cb.from_user.id), ws_id))


@router.message(Command("leave"))
async def leave_cmd(msg: Message):
    ws, uid = await _require_team(msg), msg.from_user.id
    if not ws:
        return
    if await ctx.db.member_role(ws["id"], uid) == "admin" and await ctx.db.admin_count(ws["id"]) == 1 \
            and len(await ctx.db.members(ws["id"])) > 1:
        await msg.answer("شما تنها مدیر هستید؛ اول با /role @کاربر admin مدیر دیگری تعیین کنید.")
        return
    await ctx.db.remove_member(ws["id"], uid)
    await ctx.db.ensure_user(uid)
    await msg.answer(f"از «{texts._esc(ws['name'])}» خارج شدید. کارهای باز شما بدون مسئول شد.")


async def _target(msg: Message, command: CommandObject, ws):
    tok = (command.args or "").split()
    m = await ctx.db.find_member(ws["id"], tok[0]) if tok else None
    if not m:
        await msg.answer("عضو پیدا نشد. مثال: <code>/kick @ali</code> (فهرست: /members)", parse_mode="HTML")
    return m, tok


@router.message(Command("kick"))
async def kick_cmd(msg: Message, command: CommandObject):
    ws = await _require_admin(msg)
    if not ws:
        return
    m, _ = await _target(msg, command, ws)
    if not m or m["user_id"] == msg.from_user.id:
        return
    await ctx.db.remove_member(ws["id"], m["user_id"])
    await msg.answer(f"{texts._esc(m['name'])} از تیم حذف شد.")
    await notify.send(msg.bot, m["user_id"], f"شما از تیم «{texts._esc(ws['name'])}» حذف شدید.")


@router.message(Command("role"))
async def role_cmd(msg: Message, command: CommandObject):
    ws = await _require_admin(msg)
    if not ws:
        return
    m, tok = await _target(msg, command, ws)
    if not m:
        return
    role = tok[1] if len(tok) > 1 else ""
    if role not in ROLE_NAMES:
        await msg.answer("نقش: admin یا member. مثال: <code>/role @ali admin</code>", parse_mode="HTML")
        return
    if role == "member" and m["role"] == "admin" and await ctx.db.admin_count(ws["id"]) == 1:
        await msg.answer("تیم باید حداقل یک مدیر داشته باشد.")
        return
    await ctx.db.set_role(ws["id"], m["user_id"], role)
    await msg.answer(f"نقش {texts._esc(m['name'])} شد: {ROLE_NAMES[role]}")


# ---------- برد ----------
@router.message(Command("boards"))
async def boards_cmd(msg: Message):
    ws = await _active(msg)
    boards = await ctx.db.boards(ws["id"])
    await msg.answer(f"🗂 <b>بردهای {texts._esc(ws['name'])}</b>\n" + "\n".join(
        f"• {texts._esc(b['name'])}" for b in boards) + "\n\nنمایش: <code>/board نام برد</code>",
        parse_mode="HTML")


@router.message(Command("newboard"))
async def newboard_cmd(msg: Message, command: CommandObject):
    ws = await _active(msg)
    name = (command.args or "").strip()
    if not name:
        await msg.answer("فرمت: <code>/newboard نام برد</code>", parse_mode="HTML")
        return
    if ws["kind"] == TEAM and await ctx.db.member_role(ws["id"], msg.from_user.id) != "admin":
        await msg.answer("فقط مدیر تیم می‌تواند برد جدید بسازد.")
        return
    if await ctx.db.board_by_name(ws["id"], name):
        await msg.answer("برد با این نام وجود دارد.")
        return
    from .db import PERSONAL_LISTS, TEAM_LISTS
    await ctx.db.create_board(ws["id"], name[:40], TEAM_LISTS if ws["kind"] == TEAM else PERSONAL_LISTS)
    await msg.answer(f"برد «{texts._esc(name)}» ساخته شد. کارهای آن با <code>/board {texts._esc(name)}</code> دیده می‌شود.",
                     parse_mode="HTML")


@router.message(Command("board"))
@router.message(F.text == "🗂 برد")
async def board_cmd(msg: Message, command: CommandObject | None = None):
    ws = await _active(msg)
    name = (command.args or "").strip() if command else ""
    board = (await ctx.db.board_by_name(ws["id"], name)) if name else None
    if name and not board:
        await msg.answer("برد پیدا نشد. /boards")
        return
    if not board:
        board = (await ctx.db.boards(ws["id"]))[0]
    tasks = await ctx.db.board_tasks(board["id"])
    by_list: dict[int, list] = {}
    for t in tasks:
        by_list.setdefault(t["list_id"], []).append(t)
    out = [f"🗂 <b>{texts._esc(ws['name'])} › {texts._esc(board['name'])}</b>"]
    for l in await ctx.db.lists(board["id"]):
        items = by_list.get(l["id"], [])
        out.append(f"\n<b>{texts._esc(l['name'])}</b> ({len(items)})")
        out += [texts.task_line(t, show_ws=False, show_assignee=True) for t in items[:8]]
        if len(items) > 8:
            out.append(f"… و {len(items) - 8} مورد دیگر")
    out.append("\nجزئیات/اقدام: <code>/card شماره</code>")
    await common.send_long(msg, "\n".join(out))


@router.message(Command("log"))
async def log_cmd(msg: Message):
    ws = await _active(msg)
    rows = await ctx.db.activity(ws["id"])
    names = {"created": "ساخت", "done": "انجام", "moved": "انتقال", "assigned": "اساین",
             "edited": "ویرایش", "comment": "یادداشت", "deleted": "حذف", "joined": "پیوستن",
             "left": "خروج", "team_created": "ساخت تیم"}
    await common.send_long(msg, f"🕘 <b>آخرین فعالیت‌ها — {texts._esc(ws['name'])}</b>\n" + "\n".join(
        f"{dates.fmt_dt(r['ts'])} · {texts._esc(r['name'] or '—')}: {names.get(r['action'], r['action'])}"
        + (f" #{r['task_id']}" if r["task_id"] else "") + (f" — {texts._esc(r['detail'])}" if r["detail"] and r["action"] != "assigned" else "")
        for r in rows) or "هنوز فعالیتی ثبت نشده.")


# ---------- کارت‌ها ----------
async def _task_arg(msg: Message, command: CommandObject, usage: str, need_rest: bool = False):
    """(task، باقی آرگومان‌ها)؛ در صورت آرگومان نامعتبر یا نبودن کار، پیام می‌دهد و (None،"") برمی‌گرداند."""
    parts = (command.args or "").split(None, 1)
    if not parts or not parts[0].isdigit() or (need_rest and len(parts) < 2):
        await msg.answer(f"فرمت: <code>{usage}</code>", parse_mode="HTML")
        return None, ""
    t = await ctx.db.get_task(msg.from_user.id, int(parts[0]))
    if not t:
        await msg.answer("چنین کاری پیدا نشد یا به آن دسترسی ندارید.")
        return None, ""
    return t, parts[1].strip() if len(parts) > 1 else ""


async def show_card(bot, chat_id_msg: Message, uid: int, task_id: int):
    t = await ctx.db.get_task(uid, task_id)
    if not t:
        await chat_id_msg.answer("چنین کاری پیدا نشد.")
        return
    await chat_id_msg.answer(texts.card_text(t, await ctx.db.comments(task_id)), parse_mode="HTML",
                             reply_markup=task_kb(task_id, team=t["ws_kind"] != PERSONAL))


@router.message(Command("card"))
async def card_cmd(msg: Message, command: CommandObject):
    t, _ = await _task_arg(msg, command, "/card 12")
    if t:
        await show_card(msg.bot, msg, msg.from_user.id, t["id"])


@router.message(Command("due"))
async def due_cmd(msg: Message, command: CommandObject):
    t, rest = await _task_arg(msg, command, "/due 12 فردا 9:00", need_rest=True)
    if not t:
        return
    if rest in ("-", "ندارد"):
        due = None
    else:
        dt = dates.parse_when(rest)
        if dt is None:
            await msg.answer("زمان را نفهمیدم 🤔")
            return
        due = int(dt.timestamp())
    await ctx.db.update_task(msg.from_user.id, t["id"], due_ts=due)
    await msg.answer(f"🕒 موعد کار {t['id']}: {dates.fmt_dt(due)}")
    await _tell_assignee(msg, t, f"موعد «{texts._esc(t['title'])}» به {dates.fmt_dt(due)} تغییر کرد.")


@router.message(Command("title"))
async def title_cmd(msg: Message, command: CommandObject):
    t, rest = await _task_arg(msg, command, "/title 12 عنوان جدید", need_rest=True)
    if not t:
        return
    await ctx.db.update_task(msg.from_user.id, t["id"], title=rest[:200])
    await msg.answer("عنوان به‌روز شد ✔️")


@router.message(Command("pri"))
async def pri_cmd(msg: Message, command: CommandObject):
    t, rest = await _task_arg(msg, command, "/pri 12 فوری|مهم|عادی", need_rest=True)
    if not t:
        return
    p = PRIORITY_WORDS.get(rest.lstrip("!"))
    if not p:
        await msg.answer("اولویت: فوری، مهم یا عادی")
        return
    await ctx.db.update_task(msg.from_user.id, t["id"], priority=p)
    await msg.answer(f"اولویت کار {t['id']}: {texts.PRIORITY_NAME[p]} ✔️")


@router.message(Command("move"))
async def move_cmd(msg: Message, command: CommandObject):
    t, rest = await _task_arg(msg, command, "/move 12 در حال انجام", need_rest=True)
    if not t:
        return
    lst = await ctx.db.list_by_name(t["board_id"], rest)
    if not lst:
        names = "، ".join(l["name"] for l in await ctx.db.lists(t["board_id"]))
        await msg.answer(f"لیست پیدا نشد. لیست‌ها: {texts._esc(names)}")
        return
    await _do_move(msg.bot, msg.from_user, t, lst, msg)


@router.message(Command("pass"))
async def pass_cmd(msg: Message, command: CommandObject):
    t, rest = await _task_arg(msg, command, "/pass 12 @ali", need_rest=True)
    if not t:
        return
    tok = rest.split()[0].lstrip("@")
    if tok in common.NONE_TOKENS:
        new = None
    elif tok in common.SELF_TOKENS:
        new = msg.from_user.id
    else:
        m = await ctx.db.find_member(t["ws_id"], tok)
        if not m:
            await msg.answer("عضو پیدا نشد. /members")
            return
        new = m["user_id"]
    await _do_assign(msg.bot, msg.from_user, t["id"], new, msg)


@router.message(Command("note"))
async def note_cmd(msg: Message, command: CommandObject):
    t, rest = await _task_arg(msg, command, "/note 12 متن یادداشت", need_rest=True)
    if not t:
        return
    await ctx.db.add_comment(msg.from_user.id, t["id"], rest[:500])
    await msg.answer("💬 یادداشت ثبت شد.")
    text = f"💬 {actor_name(msg.from_user)} روی «{texts._esc(t['title'])}» ({t['id']}) نوشت:\n{texts._esc(rest[:500])}"
    for target in {t["assignee_id"], t["creator_id"]}:
        await notify.send(msg.bot, target, text, exclude=msg.from_user.id)


@router.message(Command("del"))
async def del_cmd(msg: Message, command: CommandObject):
    t, _ = await _task_arg(msg, command, "/del 12")
    if not t:
        return
    if await ctx.db.delete(msg.from_user.id, t["id"]):
        await msg.answer("🗑 حذف شد.")
    else:
        await msg.answer("فقط سازنده کار یا مدیر تیم می‌تواند آن را حذف کند.")


async def _tell_assignee(msg, t, text: str):
    await notify.send(msg.bot, t["assignee_id"], f"✏️ {actor_name(msg.from_user)}: {text}",
                      exclude=msg.from_user.id)


async def _do_assign(bot, user, task_id: int, new, reply: Message):
    t = await ctx.db.assign(user.id, task_id, new)
    if not t:
        await reply.answer("انجام نشد (دسترسی یا عضویت).")
        return
    nm = "بدون مسئول"
    if new:
        u = await ctx.db.get_user(new)
        nm = texts._esc(u["name"] or u["username"] or new)
    await reply.answer(f"👤 مسئول کار {task_id}: {nm}")
    await common.announce_assignment(bot, task_id, user, new, passed=True)


async def _do_move(bot, user, t, lst, reply: Message):
    if lst["is_done"]:
        await _do_done(bot, user, t["id"], reply)
        return
    if not await ctx.db.move(user.id, t["id"], lst["id"]):
        await reply.answer("انتقال انجام نشد.")
        return
    await reply.answer(f"➡️ کار {t['id']} → {texts._esc(lst['name'])}")
    if lst["kind"] == "review":
        await notify.send(bot, t["creator_id"],
                          f"👀 {actor_name(user)} «{texts._esc(t['title'])}» ({t['id']}) را به بازبینی برد.",
                          exclude=user.id)


async def _do_done(bot, user, task_id: int, reply: Message):
    res = await ctx.db.complete(user.id, task_id)
    if not res:
        await reply.answer("قبلاً انجام شده بود یا دسترسی ندارید.")
        return
    t, next_id = res
    await reply.answer(f"آفرین! ✅ «{texts._esc(t['title'])}» انجام شد."
                       + (f"\n🔁 نوبت بعدی ساخته شد: {dates.fmt_dt(next_due(t))}" if next_id else ""))
    await notify.send(bot, t["creator_id"], f"✅ {actor_name(user)} کار «{texts._esc(t['title'])}» "
                      f"({t['id']}) را انجام داد.", exclude=user.id)


def next_due(t) -> int:
    from .db import next_due as _nd
    return _nd(t["due_ts"], t["recur"])


# ---------- دکمه‌ها ----------
def _cb_id(cb: CallbackQuery, idx: int = 1) -> int:
    return int(cb.data.split(":")[idx])


async def _strip(cb: CallbackQuery):
    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("done:"))
async def cb_done(cb: CallbackQuery):
    await cb.answer()
    await _strip(cb)
    await _do_done(cb.bot, cb.from_user, _cb_id(cb), cb.message)


@router.callback_query(F.data.startswith("snooze:"))
async def cb_snooze(cb: CallbackQuery):
    import time
    ok = await ctx.db.update_task(cb.from_user.id, _cb_id(cb), due_ts=int(time.time()) + 600)
    await cb.answer("۱۰ دقیقه دیگر یادآوری می‌کنم ⏰" if ok else "انجام نشد")
    await _strip(cb)


@router.callback_query(F.data.startswith("start:"))
async def cb_start(cb: CallbackQuery):
    t = await ctx.db.get_task(cb.from_user.id, _cb_id(cb))
    lst = t and await ctx.db.list_by_kind(t["board_id"], "doing")
    await cb.answer()
    if t and lst:
        await _do_move(cb.bot, cb.from_user, t, lst, cb.message)


@router.callback_query(F.data.startswith("next:"))
async def cb_next(cb: CallbackQuery):
    t = await ctx.db.get_task(cb.from_user.id, _cb_id(cb))
    nxt = t and await ctx.db.next_list(t["list_id"])
    await cb.answer("این آخرین لیست است" if t and not nxt else None)
    if t and nxt:
        await _do_move(cb.bot, cb.from_user, t, nxt, cb.message)


@router.callback_query(F.data.startswith("pass:"))
async def cb_pass(cb: CallbackQuery):
    t = await ctx.db.get_task(cb.from_user.id, _cb_id(cb))
    if not t:
        await cb.answer("دسترسی ندارید")
        return
    await cb.answer()
    await cb.message.answer(f"کار {t['id']} را به چه کسی پاس بدهم؟",
                            reply_markup=members_kb(t["id"], await ctx.db.members(t["ws_id"]),
                                                    exclude=t["assignee_id"]))


@router.callback_query(F.data.startswith("passto:"))
async def cb_passto(cb: CallbackQuery):
    await cb.answer()
    await _strip(cb)
    await _do_assign(cb.bot, cb.from_user, _cb_id(cb), _cb_id(cb, 2) or None, cb.message)


@router.callback_query(F.data.startswith("card:"))
async def cb_card(cb: CallbackQuery):
    await cb.answer()
    await show_card(cb.bot, cb.message, cb.from_user.id, _cb_id(cb))


@router.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery):
    ok = await ctx.db.delete(cb.from_user.id, _cb_id(cb))
    await cb.answer("حذف شد 🗑" if ok else "فقط سازنده یا مدیر می‌تواند حذف کند")
    if ok:
        await _strip(cb)
