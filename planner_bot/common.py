from __future__ import annotations

from aiogram.filters import CommandObject
from aiogram.types import Message

from . import ctx, notify, texts
from .db import PERSONAL
from .keyboards import task_kb
from .taskparse import clean_category

NONE_TOKENS = {"-", "هیچکس", "none"}
SELF_TOKENS = {"من", "me"}


def actor_name(user) -> str:
    return texts._esc(user.full_name or (f"@{user.username}" if user.username else "یک عضو"))


async def resolve_assignee(ws, uid: int, mentions: list[str]):
    """(assignee_id، mention ناشناخته یا None). پیش‌فرض: خود کاربر؛ «@-» یعنی بدون مسئول."""
    if ws["kind"] == PERSONAL or not mentions:
        return uid, None
    tok = mentions[0]
    if tok in NONE_TOKENS:
        return None, None
    if tok in SELF_TOKENS:
        return uid, None
    m = await ctx.db.find_member(ws["id"], tok)
    return (m["user_id"], None) if m else (uid, tok)


async def filter_arg(uid: int, command: CommandObject | None):
    """آرگومان دستور را به (دسته، شناسه فضا) تبدیل می‌کند: نام فضا یا دسته."""
    if command is None or not command.args:
        return None, None
    arg = command.args.strip().lstrip("#")
    for w in await ctx.db.my_workspaces(uid):
        if w["name"].lower() == arg.lower():
            return None, w["id"]
    return clean_category(arg), None


async def send_long(msg: Message, text: str, limit: int = 3800, **kw):
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > limit and chunk:
            await msg.answer(chunk, parse_mode="HTML", **kw)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await msg.answer(chunk, parse_mode="HTML", **kw)


async def announce_assignment(bot, task_id: int, actor, to_user: int | None, passed: bool = False):
    """اعلان اساین/پاس به مسئول جدید (اگر خودِ عامل نباشد)."""
    if not to_user or to_user == actor.id:
        return
    t = await ctx.db.get_task(to_user, task_id)
    if not t:
        return
    head = "🔁 کاری به شما پاس داده شد" if passed else "📌 کار جدید برای شما"
    await notify.send(bot, to_user, f"{head} — از طرف {actor_name(actor)}\n"
                      f"{texts.task_line(t, show_ws=False)}\n🏢 {texts._esc(t['ws_name'])} › "
                      f"{texts._esc(t['list_name'])}\n🕒 {texts.dates.fmt_dt(t['due_ts'])}",
                      task_kb(task_id, team=t["ws_kind"] != PERSONAL))
