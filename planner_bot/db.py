from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta

import aiosqlite
import jdatetime

from .config import DEFAULT_EVENING, DEFAULT_MORNING, TZ

DEFAULT_CATEGORY = "عمومی"
PERSONAL = "personal"
TEAM = "team"

# (نام، نوع، آیا ستون «انجام‌شده» است)
TEAM_LISTS = [("📥 بک‌لاگ", "backlog", 0), ("📋 برای انجام", "todo", 0),
              ("🔄 در حال انجام", "doing", 0), ("👀 بازبینی", "review", 0),
              ("✅ انجام شد", "done", 1)]
PERSONAL_LISTS = [("📋 برای انجام", "todo", 0), ("🔄 در حال انجام", "doing", 0),
                  ("✅ انجام شد", "done", 1)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  username TEXT,
  morning TEXT NOT NULL,
  evening TEXT NOT NULL,
  last_morning TEXT DEFAULT '',
  last_evening TEXT DEFAULT '',
  active_ws INTEGER
);
CREATE TABLE IF NOT EXISTS workspaces(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  owner_id INTEGER NOT NULL,
  invite_code TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS members(
  ws_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  PRIMARY KEY(ws_id, user_id)
);
CREATE TABLE IF NOT EXISTS boards(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ws_id INTEGER NOT NULL,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lists(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  position INTEGER NOT NULL,
  is_done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  due_ts INTEGER,
  created_ts INTEGER NOT NULL,
  done_ts INTEGER,
  notified INTEGER NOT NULL DEFAULT 0,
  category TEXT NOT NULL DEFAULT 'عمومی',
  ws_id INTEGER,
  board_id INTEGER,
  list_id INTEGER,
  assignee_id INTEGER,
  creator_id INTEGER,
  priority INTEGER NOT NULL DEFAULT 3,
  est_min INTEGER,
  recur TEXT,
  description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS categories(
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  emoji TEXT NOT NULL DEFAULT '📌',
  PRIMARY KEY(user_id, name)
);
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ws_id INTEGER NOT NULL,
  task_id INTEGER,
  user_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  ts INTEGER NOT NULL
);
"""

# ستون‌های اضافه‌شده در نسخه‌های جدید (برای مهاجرت دیتابیس قدیمی)
_TASK_COLS = {
    "category": "TEXT NOT NULL DEFAULT 'عمومی'", "ws_id": "INTEGER", "board_id": "INTEGER",
    "list_id": "INTEGER", "assignee_id": "INTEGER", "creator_id": "INTEGER",
    "priority": "INTEGER NOT NULL DEFAULT 3", "est_min": "INTEGER", "recur": "TEXT",
    "description": "TEXT NOT NULL DEFAULT ''",
}
_USER_COLS = {"name": "TEXT NOT NULL DEFAULT ''", "username": "TEXT", "active_ws": "INTEGER"}

_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks(assignee_id, done_ts);
CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(due_ts, notified);
CREATE INDEX IF NOT EXISTS ix_tasks_board ON tasks(board_id, list_id);
CREATE INDEX IF NOT EXISTS ix_lists_board ON lists(board_id, position);
"""

_TASK_SELECT = (
    "SELECT t.*, l.name AS list_name, l.kind AS list_kind, w.name AS ws_name, w.kind AS ws_kind, "
    "a.name AS assignee_name, a.username AS assignee_username "
    "FROM tasks t JOIN workspaces w ON w.id=t.ws_id "
    "LEFT JOIN lists l ON l.id=t.list_id LEFT JOIN users a ON a.user_id=t.assignee_id ")

RECUR = {"daily": 1, "weekly": 7, "monthly": 0}


def next_due(due_ts: int, recur: str) -> int:
    dt = datetime.fromtimestamp(due_ts, TZ)
    if recur == "monthly":
        j = jdatetime.datetime.fromgregorian(datetime=dt)
        month, year = (j.month % 12) + 1, j.year + (1 if j.month == 12 else 0)
        day = j.day
        while True:
            try:
                nj = j.replace(year=year, month=month, day=day)
                break
            except ValueError:
                day -= 1
        return int(nj.togregorian().replace(tzinfo=TZ).timestamp())
    return int((dt + timedelta(days=RECUR[recur])).timestamp())


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection

    async def open(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._add_columns("tasks", _TASK_COLS)
        await self._add_columns("users", _USER_COLS)
        await self.conn.executescript(_INDEXES)
        await self.conn.commit()
        await self._migrate_legacy()

    async def close(self):
        await self.conn.close()

    async def _add_columns(self, table: str, cols: dict):
        have = {r["name"] for r in await self._all(f"PRAGMA table_info({table})")}
        for col, ddl in cols.items():
            if col not in have:
                await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    async def _migrate_legacy(self):
        """کارهای نسخه‌های قبلی را به فضای شخصی صاحبشان منتقل می‌کند."""
        for r in await self._all("SELECT DISTINCT user_id FROM tasks WHERE ws_id IS NULL"):
            uid = r["user_id"]
            await self.ensure_user(uid)
            ws = await self.personal_ws(uid)
            board = await self.default_board(ws)
            todo = await self.entry_list(board)
            done = await self.done_list(board)
            await self._run(
                "UPDATE tasks SET ws_id=?, board_id=?, assignee_id=user_id, creator_id=user_id, "
                "list_id=CASE WHEN done_ts IS NULL THEN ? ELSE ? END "
                "WHERE user_id=? AND ws_id IS NULL", ws, board, todo, done, uid)

    async def _all(self, sql, *args):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchall()

    async def _one(self, sql, *args):
        rows = await self._all(sql, *args)
        return rows[0] if rows else None

    async def _run(self, sql, *args):
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur

    # ---------- کاربران ----------
    async def ensure_user(self, user_id: int, name: str = "", username: str | None = None):
        await self._run(
            "INSERT OR IGNORE INTO users(user_id,name,username,morning,evening) VALUES(?,?,?,?,?)",
            user_id, name, username, DEFAULT_MORNING, DEFAULT_EVENING)
        if name or username:
            await self._run("UPDATE users SET name=COALESCE(NULLIF(?,''),name), username=? "
                            "WHERE user_id=?", name, username, user_id)
        user = await self.get_user(user_id)
        if user["active_ws"] is None or not await self.member_role(user["active_ws"], user_id):
            ws = await self._personal_ws_or_none(user_id)
            if ws is None:
                ws = await self._make_workspace("شخصی", PERSONAL, user_id, PERSONAL_LISTS,
                                                "کارهای من")
            await self._run("UPDATE users SET active_ws=? WHERE user_id=?", ws, user_id)

    async def get_user(self, user_id: int):
        return await self._one("SELECT * FROM users WHERE user_id=?", user_id)

    async def all_users(self):
        return await self._all("SELECT * FROM users")

    async def set_time(self, user_id: int, field: str, value: str):
        assert field in ("morning", "evening")
        await self._run(f"UPDATE users SET {field}=? WHERE user_id=?", value, user_id)

    async def mark_digest(self, user_id: int, field: str, day: str):
        assert field in ("last_morning", "last_evening")
        await self._run(f"UPDATE users SET {field}=? WHERE user_id=?", day, user_id)

    # ---------- فضای کاری ----------
    async def _personal_ws_or_none(self, uid: int):
        r = await self._one("SELECT id FROM workspaces WHERE kind=? AND owner_id=?", PERSONAL, uid)
        return r["id"] if r else None

    async def personal_ws(self, uid: int) -> int:
        return await self._personal_ws_or_none(uid)

    async def _make_workspace(self, name, kind, owner, lists, board_name) -> int:
        code = secrets.token_urlsafe(6) if kind == TEAM else None
        cur = await self._run("INSERT INTO workspaces(name,kind,owner_id,invite_code) VALUES(?,?,?,?)",
                              name, kind, owner, code)
        ws = cur.lastrowid
        await self._run("INSERT INTO members(ws_id,user_id,role) VALUES(?,?, 'admin')", ws, owner)
        await self.create_board(ws, board_name, lists)
        return ws

    async def create_team(self, uid: int, name: str) -> int:
        ws = await self._make_workspace(name, TEAM, uid, TEAM_LISTS, "عمومی")
        await self._run("UPDATE users SET active_ws=? WHERE user_id=?", ws, uid)
        await self.log(ws, None, uid, "team_created", name)
        return ws

    async def get_ws(self, ws_id: int):
        return await self._one("SELECT * FROM workspaces WHERE id=?", ws_id)

    async def active_ws(self, uid: int):
        return await self._one(
            "SELECT w.* FROM users u JOIN workspaces w ON w.id=u.active_ws WHERE u.user_id=?", uid)

    async def set_active_ws(self, uid: int, ws_id: int) -> bool:
        if not await self.member_role(ws_id, uid):
            return False
        await self._run("UPDATE users SET active_ws=? WHERE user_id=?", ws_id, uid)
        return True

    async def my_workspaces(self, uid: int):
        return await self._all(
            "SELECT w.*, m.role FROM workspaces w JOIN members m ON m.ws_id=w.id AND m.user_id=? "
            "ORDER BY w.kind DESC, w.id", uid)

    async def ws_by_invite(self, code: str):
        return await self._one("SELECT * FROM workspaces WHERE invite_code=?", code)

    async def reset_invite(self, ws_id: int) -> str:
        code = secrets.token_urlsafe(6)
        await self._run("UPDATE workspaces SET invite_code=? WHERE id=? AND kind=?",
                        code, ws_id, TEAM)
        return code

    async def member_role(self, ws_id: int, uid: int) -> str | None:
        r = await self._one("SELECT role FROM members WHERE ws_id=? AND user_id=?", ws_id, uid)
        return r["role"] if r else None

    async def join(self, ws_id: int, uid: int) -> bool:
        """True اگر تازه عضو شد."""
        if await self.member_role(ws_id, uid):
            return False
        await self._run("INSERT INTO members(ws_id,user_id,role) VALUES(?,?, 'member')", ws_id, uid)
        await self.log(ws_id, None, uid, "joined")
        return True

    async def members(self, ws_id: int):
        return await self._all(
            "SELECT m.user_id, m.role, u.name, u.username FROM members m "
            "LEFT JOIN users u ON u.user_id=m.user_id WHERE m.ws_id=? ORDER BY m.role, u.name", ws_id)

    async def find_member(self, ws_id: int, token: str):
        token = token.lstrip("@").strip().lower()
        for m in await self.members(ws_id):
            if token and token in ((m["username"] or "").lower(), (m["name"] or "").lower()):
                return m
        return None

    async def remove_member(self, ws_id: int, uid: int):
        await self._run("DELETE FROM members WHERE ws_id=? AND user_id=?", ws_id, uid)
        await self._run("UPDATE tasks SET assignee_id=NULL WHERE ws_id=? AND assignee_id=? "
                        "AND done_ts IS NULL", ws_id, uid)
        await self.log(ws_id, None, uid, "left")

    async def set_role(self, ws_id: int, uid: int, role: str):
        await self._run("UPDATE members SET role=? WHERE ws_id=? AND user_id=?", role, ws_id, uid)

    async def admin_count(self, ws_id: int) -> int:
        return (await self._one("SELECT COUNT(*) c FROM members WHERE ws_id=? AND role='admin'",
                                ws_id))["c"]

    # ---------- بردها و لیست‌ها ----------
    async def create_board(self, ws_id: int, name: str, lists=TEAM_LISTS) -> int:
        cur = await self._run("INSERT INTO boards(ws_id,name) VALUES(?,?)", ws_id, name)
        board = cur.lastrowid
        for pos, (lname, kind, is_done) in enumerate(lists):
            await self._run("INSERT INTO lists(board_id,name,kind,position,is_done) VALUES(?,?,?,?,?)",
                            board, lname, kind, pos, is_done)
        return board

    async def boards(self, ws_id: int):
        return await self._all("SELECT * FROM boards WHERE ws_id=? ORDER BY id", ws_id)

    async def default_board(self, ws_id: int) -> int:
        return (await self._one("SELECT id FROM boards WHERE ws_id=? ORDER BY id LIMIT 1", ws_id))["id"]

    async def board_by_name(self, ws_id: int, name: str):
        return await self._one("SELECT * FROM boards WHERE ws_id=? AND name=?", ws_id, name.strip())

    async def lists(self, board_id: int):
        return await self._all("SELECT * FROM lists WHERE board_id=? ORDER BY position", board_id)

    async def entry_list(self, board_id: int) -> int:
        r = (await self._one("SELECT id FROM lists WHERE board_id=? AND kind='todo' LIMIT 1", board_id)
             or await self._one("SELECT id FROM lists WHERE board_id=? AND is_done=0 "
                                "ORDER BY position LIMIT 1", board_id))
        return r["id"]

    async def done_list(self, board_id: int) -> int:
        return (await self._one("SELECT id FROM lists WHERE board_id=? AND is_done=1 LIMIT 1",
                                board_id))["id"]

    async def list_by_kind(self, board_id: int, kind: str):
        return await self._one("SELECT * FROM lists WHERE board_id=? AND kind=?", board_id, kind)

    async def next_list(self, list_id: int):
        cur = await self._one("SELECT * FROM lists WHERE id=?", list_id)
        return await self._one("SELECT * FROM lists WHERE board_id=? AND position>? "
                               "ORDER BY position LIMIT 1", cur["board_id"], cur["position"])

    async def get_list(self, list_id: int):
        return await self._one("SELECT * FROM lists WHERE id=?", list_id)

    async def list_by_name(self, board_id: int, name: str):
        name = name.strip()
        for l in await self.lists(board_id):
            if name and (name in l["name"] or l["kind"] == name):
                return l
        return None

    # ---------- کارها ----------
    async def add_task(self, creator_id: int, ws_id: int, title: str, due_ts: int | None,
                       category: str = DEFAULT_CATEGORY, assignee_id: int | None = None,
                       priority: int = 3, est_min: int | None = None, recur: str | None = None,
                       notify: bool = True, board_id: int | None = None,
                       description: str = "") -> int:
        board_id = board_id or await self.default_board(ws_id)
        list_id = await self.entry_list(board_id)
        await self._run("INSERT OR IGNORE INTO categories(user_id,name) VALUES(?,?)",
                        creator_id, category)
        cur = await self._run(
            "INSERT INTO tasks(user_id,title,due_ts,created_ts,category,ws_id,board_id,list_id,"
            "assignee_id,creator_id,priority,est_min,recur,notified,description) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            creator_id, title, due_ts, int(time.time()), category, ws_id, board_id, list_id,
            assignee_id, creator_id, priority, est_min, recur, 0 if notify else 1, description)
        await self.log(ws_id, cur.lastrowid, creator_id, "created", title)
        return cur.lastrowid

    async def exists(self, ws_id: int, assignee_id: int | None, title: str, due_ts: int | None) -> bool:
        return bool(await self._all(
            "SELECT 1 FROM tasks WHERE ws_id=? AND assignee_id IS ? AND title=? AND due_ts IS ?",
            ws_id, assignee_id, title, due_ts))

    async def get_task(self, uid: int, task_id: int):
        """کار را فقط اگر uid عضو فضای آن باشد برمی‌گرداند."""
        return await self._one(
            _TASK_SELECT + "JOIN members m ON m.ws_id=t.ws_id AND m.user_id=? WHERE t.id=?",
            uid, task_id)

    @staticmethod
    def _filters(category: str | None, ws_id: int | None):
        sql, args = "", []
        if category:
            sql += " AND t.category=?"
            args.append(category)
        if ws_id:
            sql += " AND t.ws_id=?"
            args.append(ws_id)
        return sql, args

    async def open_tasks(self, uid: int, category=None, ws_id=None):
        f, a = self._filters(category, ws_id)
        return await self._all(
            _TASK_SELECT + "WHERE t.assignee_id=? AND t.done_ts IS NULL" + f +
            " ORDER BY t.due_ts IS NULL, t.due_ts, t.priority, t.id", uid, *a)

    async def tasks_between(self, uid: int, start: int, end: int, category=None, ws_id=None):
        f, a = self._filters(category, ws_id)
        return await self._all(
            _TASK_SELECT + "WHERE t.assignee_id=? AND t.due_ts>=? AND t.due_ts<?" + f +
            " ORDER BY t.done_ts IS NOT NULL, t.priority, t.due_ts", uid, start, end, *a)

    async def overdue(self, uid: int, before: int, category=None, ws_id=None):
        f, a = self._filters(category, ws_id)
        return await self._all(
            _TASK_SELECT + "WHERE t.assignee_id=? AND t.done_ts IS NULL AND t.due_ts<?" + f +
            " ORDER BY t.due_ts", uid, before, *a)

    async def board_tasks(self, board_id: int):
        return await self._all(
            _TASK_SELECT + "JOIN lists ll ON ll.id=t.list_id WHERE t.board_id=? "
            "AND (t.done_ts IS NULL OR t.done_ts>?) ORDER BY ll.position, t.priority, t.due_ts",
            board_id, int(time.time()) - 3 * 86400)

    async def categories(self, uid: int):
        return await self._all(
            "SELECT c.name, c.emoji, COUNT(t.id) AS open_count FROM categories c "
            "LEFT JOIN tasks t ON t.assignee_id=c.user_id AND t.category=c.name AND t.done_ts IS NULL "
            "WHERE c.user_id=? GROUP BY c.name ORDER BY c.name", uid)

    async def set_category(self, uid: int, name: str, emoji: str | None):
        await self._run("INSERT OR IGNORE INTO categories(user_id,name) VALUES(?,?)", uid, name)
        if emoji:
            await self._run("UPDATE categories SET emoji=? WHERE user_id=? AND name=?",
                            emoji, uid, name)

    async def stats_by_category(self, uid: int, start: int, end: int):
        return await self._all(
            "SELECT category, COUNT(*) total, COALESCE(SUM(done_ts IS NOT NULL),0) done "
            "FROM tasks WHERE assignee_id=? AND due_ts>=? AND due_ts<? GROUP BY category "
            "ORDER BY total DESC", uid, start, end)

    async def stats(self, uid: int, start: int, end: int):
        r = await self._one(
            "SELECT COUNT(*) total, COALESCE(SUM(done_ts IS NOT NULL),0) done "
            "FROM tasks WHERE assignee_id=? AND due_ts>=? AND due_ts<?", uid, start, end)
        return r["total"], r["done"]

    async def done_days(self, uid: int):
        rows = await self._all("SELECT done_ts FROM tasks WHERE assignee_id=? AND done_ts IS NOT NULL",
                               uid)
        return [r["done_ts"] for r in rows]

    # ---------- تغییر وضعیت ----------
    async def complete(self, uid: int, task_id: int):
        """کار را انجام‌شده می‌کند. (کار قبلی، شناسه کار تکرارشونده بعدی) یا None."""
        t = await self.get_task(uid, task_id)
        if not t or t["done_ts"]:
            return None
        await self._run("UPDATE tasks SET done_ts=?, list_id=? WHERE id=?",
                        int(time.time()), await self.done_list(t["board_id"]), task_id)
        await self.log(t["ws_id"], task_id, uid, "done", t["title"])
        next_id = None
        if t["recur"] and t["due_ts"]:
            next_id = await self.add_task(
                t["creator_id"], t["ws_id"], t["title"], next_due(t["due_ts"], t["recur"]),
                t["category"], t["assignee_id"], t["priority"], t["est_min"], t["recur"],
                notify=True, board_id=t["board_id"], description=t["description"])
        return t, next_id

    async def move(self, uid: int, task_id: int, list_id: int):
        """انتقال به لیست دیگر (غیر از انجام‌شده). کار را برمی‌گرداند یا None."""
        t = await self.get_task(uid, task_id)
        lst = await self.get_list(list_id)
        if not t or not lst or lst["board_id"] != t["board_id"] or lst["is_done"]:
            return None
        await self._run("UPDATE tasks SET list_id=?, done_ts=NULL WHERE id=?", list_id, task_id)
        await self.log(t["ws_id"], task_id, uid, "moved", lst["name"])
        return t

    async def assign(self, uid: int, task_id: int, new_assignee: int | None):
        t = await self.get_task(uid, task_id)
        if not t or (new_assignee and not await self.member_role(t["ws_id"], new_assignee)):
            return None
        await self._run("UPDATE tasks SET assignee_id=?, notified=0 WHERE id=?", new_assignee, task_id)
        await self.log(t["ws_id"], task_id, uid, "assigned", str(new_assignee or ""))
        return t

    async def update_task(self, uid: int, task_id: int, **fields):
        allowed = {"title", "due_ts", "priority", "est_min", "category", "description", "recur"}
        t = await self.get_task(uid, task_id)
        if not t or not fields or set(fields) - allowed:
            return None
        if "due_ts" in fields:
            fields["notified"] = 0
        sets = ", ".join(f"{k}=?" for k in fields)
        await self._run(f"UPDATE tasks SET {sets} WHERE id=?", *fields.values(), task_id)
        await self.log(t["ws_id"], task_id, uid, "edited", ",".join(fields))
        return t

    async def delete(self, uid: int, task_id: int) -> bool:
        """فقط سازنده یا مدیر فضا."""
        t = await self.get_task(uid, task_id)
        if not t or not (t["creator_id"] == uid or await self.member_role(t["ws_id"], uid) == "admin"):
            return False
        await self._run("DELETE FROM tasks WHERE id=?", task_id)
        await self._run("DELETE FROM comments WHERE task_id=?", task_id)
        await self.log(t["ws_id"], None, uid, "deleted", t["title"])
        return True

    async def reschedule(self, uid: int, task_id: int, due_ts: int):
        return await self.update_task(uid, task_id, due_ts=due_ts)

    # ---------- یادآوری ----------
    async def due_unnotified(self, now_ts: int):
        return await self._all(
            _TASK_SELECT + "WHERE t.done_ts IS NULL AND t.notified=0 AND t.assignee_id IS NOT NULL "
            "AND t.due_ts IS NOT NULL AND t.due_ts<=?", now_ts)

    async def mark_notified(self, task_id: int):
        await self._run("UPDATE tasks SET notified=1 WHERE id=?", task_id)

    # ---------- کامنت و فعالیت ----------
    async def add_comment(self, uid: int, task_id: int, text: str):
        t = await self.get_task(uid, task_id)
        if not t:
            return None
        await self._run("INSERT INTO comments(task_id,user_id,text,ts) VALUES(?,?,?,?)",
                        task_id, uid, text, int(time.time()))
        await self.log(t["ws_id"], task_id, uid, "comment", text[:80])
        return t

    async def comments(self, task_id: int, limit: int = 5):
        return await self._all(
            "SELECT c.*, u.name FROM comments c LEFT JOIN users u ON u.user_id=c.user_id "
            "WHERE c.task_id=? ORDER BY c.id DESC LIMIT ?", task_id, limit)

    async def log(self, ws_id: int, task_id: int | None, uid: int | None, action: str, detail: str = ""):
        await self._run("INSERT INTO activity(ws_id,task_id,user_id,action,detail,ts) VALUES(?,?,?,?,?,?)",
                        ws_id, task_id, uid, action, detail, int(time.time()))

    async def activity(self, ws_id: int, limit: int = 15):
        return await self._all(
            "SELECT a.*, u.name FROM activity a LEFT JOIN users u ON u.user_id=a.user_id "
            "WHERE a.ws_id=? ORDER BY a.id DESC LIMIT ?", ws_id, limit)
