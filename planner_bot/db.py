from __future__ import annotations

import time

import aiosqlite

DEFAULT_CATEGORY = "عمومی"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  morning TEXT NOT NULL,
  evening TEXT NOT NULL,
  last_morning TEXT DEFAULT '',
  last_evening TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  due_ts INTEGER,
  created_ts INTEGER NOT NULL,
  done_ts INTEGER,
  notified INTEGER NOT NULL DEFAULT 0,
  category TEXT NOT NULL DEFAULT 'عمومی'
);
CREATE TABLE IF NOT EXISTS categories(
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  emoji TEXT NOT NULL DEFAULT '📌',
  PRIMARY KEY(user_id, name)
);
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(user_id, done_ts);
CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(due_ts, notified);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection

    async def open(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        cols = [r["name"] for r in await self._all("PRAGMA table_info(tasks)")]
        if "category" not in cols:  # مهاجرت از نسخه قبلی
            await self.conn.execute(
                f"ALTER TABLE tasks ADD COLUMN category TEXT NOT NULL DEFAULT '{DEFAULT_CATEGORY}'")
        await self.conn.commit()

    async def close(self):
        await self.conn.close()

    async def _all(self, sql, *args):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchall()

    async def _run(self, sql, *args):
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur

    # --- users
    async def ensure_user(self, user_id: int, morning: str, evening: str):
        await self._run("INSERT OR IGNORE INTO users(user_id,morning,evening) VALUES(?,?,?)",
                        user_id, morning, evening)

    async def all_users(self):
        return await self._all("SELECT * FROM users")

    async def set_time(self, user_id: int, field: str, value: str):
        assert field in ("morning", "evening")
        await self._run(f"UPDATE users SET {field}=? WHERE user_id=?", value, user_id)

    async def mark_digest(self, user_id: int, field: str, day: str):
        assert field in ("last_morning", "last_evening")
        await self._run(f"UPDATE users SET {field}=? WHERE user_id=?", day, user_id)

    # --- tasks
    async def add_task(self, user_id: int, title: str, due_ts: int | None,
                       category: str = DEFAULT_CATEGORY, notify: bool = True) -> int:
        await self._run("INSERT OR IGNORE INTO categories(user_id,name) VALUES(?,?)",
                        user_id, category)
        cur = await self._run(
            "INSERT INTO tasks(user_id,title,due_ts,created_ts,category,notified) "
            "VALUES(?,?,?,?,?,?)",
            user_id, title, due_ts, int(time.time()), category, 0 if notify else 1)
        return cur.lastrowid

    async def exists(self, user_id: int, title: str, due_ts: int | None) -> bool:
        rows = await self._all(
            "SELECT 1 FROM tasks WHERE user_id=? AND title=? AND due_ts IS ?",
            user_id, title, due_ts)
        return bool(rows)

    async def get_task(self, user_id: int, task_id: int):
        rows = await self._all("SELECT * FROM tasks WHERE id=? AND user_id=?", task_id, user_id)
        return rows[0] if rows else None

    @staticmethod
    def _cat(category: str | None):
        return (" AND category=?", (category,)) if category else ("", ())

    async def open_tasks(self, user_id: int, category: str | None = None):
        c, a = self._cat(category)
        return await self._all(
            "SELECT * FROM tasks WHERE user_id=? AND done_ts IS NULL" + c +
            " ORDER BY due_ts IS NULL, due_ts, id", user_id, *a)

    async def tasks_between(self, user_id: int, start: int, end: int, category: str | None = None):
        c, a = self._cat(category)
        return await self._all(
            "SELECT * FROM tasks WHERE user_id=? AND due_ts>=? AND due_ts<?" + c +
            " ORDER BY due_ts", user_id, start, end, *a)

    async def overdue(self, user_id: int, before: int, category: str | None = None):
        c, a = self._cat(category)
        return await self._all(
            "SELECT * FROM tasks WHERE user_id=? AND done_ts IS NULL AND due_ts<?" + c +
            " ORDER BY due_ts", user_id, before, *a)

    async def categories(self, user_id: int):
        """[(نام، ایموجی، تعداد کار باز)] شامل دسته‌های بدون کار."""
        return await self._all(
            "SELECT c.name, c.emoji, COUNT(t.id) AS open_count FROM categories c "
            "LEFT JOIN tasks t ON t.user_id=c.user_id AND t.category=c.name AND t.done_ts IS NULL "
            "WHERE c.user_id=? GROUP BY c.name ORDER BY c.name", user_id)

    async def set_category(self, user_id: int, name: str, emoji: str | None):
        await self._run("INSERT OR IGNORE INTO categories(user_id,name) VALUES(?,?)", user_id, name)
        if emoji:
            await self._run("UPDATE categories SET emoji=? WHERE user_id=? AND name=?",
                            emoji, user_id, name)

    async def stats_by_category(self, user_id: int, start: int, end: int):
        return await self._all(
            "SELECT category, COUNT(*) total, COALESCE(SUM(done_ts IS NOT NULL),0) done "
            "FROM tasks WHERE user_id=? AND due_ts>=? AND due_ts<? GROUP BY category "
            "ORDER BY total DESC", user_id, start, end)

    async def complete(self, user_id: int, task_id: int) -> bool:
        cur = await self._run(
            "UPDATE tasks SET done_ts=? WHERE id=? AND user_id=? AND done_ts IS NULL",
            int(time.time()), task_id, user_id)
        return cur.rowcount > 0

    async def delete(self, user_id: int, task_id: int) -> bool:
        cur = await self._run("DELETE FROM tasks WHERE id=? AND user_id=?", task_id, user_id)
        return cur.rowcount > 0

    async def reschedule(self, user_id: int, task_id: int, due_ts: int):
        await self._run("UPDATE tasks SET due_ts=?, notified=0 WHERE id=? AND user_id=?",
                        due_ts, task_id, user_id)

    async def due_unnotified(self, now_ts: int):
        return await self._all(
            "SELECT * FROM tasks WHERE done_ts IS NULL AND notified=0 "
            "AND due_ts IS NOT NULL AND due_ts<=?", now_ts)

    async def mark_notified(self, task_id: int):
        await self._run("UPDATE tasks SET notified=1 WHERE id=?", task_id)

    async def stats(self, user_id: int, start: int, end: int):
        """کارهایی که موعدشان در بازه است: (کل، انجام‌شده)."""
        r = (await self._all(
            "SELECT COUNT(*) total, COALESCE(SUM(done_ts IS NOT NULL),0) done "
            "FROM tasks WHERE user_id=? AND due_ts>=? AND due_ts<?", user_id, start, end))[0]
        return r["total"], r["done"]

    async def done_days(self, user_id: int):
        rows = await self._all("SELECT done_ts FROM tasks WHERE user_id=? AND done_ts IS NOT NULL",
                               user_id)
        return [r["done_ts"] for r in rows]
