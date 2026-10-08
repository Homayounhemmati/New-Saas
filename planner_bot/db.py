import time

import aiosqlite

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
  notified INTEGER NOT NULL DEFAULT 0
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
    async def add_task(self, user_id: int, title: str, due_ts: int | None) -> int:
        cur = await self._run(
            "INSERT INTO tasks(user_id,title,due_ts,created_ts) VALUES(?,?,?,?)",
            user_id, title, due_ts, int(time.time()))
        return cur.lastrowid

    async def get_task(self, user_id: int, task_id: int):
        rows = await self._all("SELECT * FROM tasks WHERE id=? AND user_id=?", task_id, user_id)
        return rows[0] if rows else None

    async def open_tasks(self, user_id: int):
        return await self._all(
            "SELECT * FROM tasks WHERE user_id=? AND done_ts IS NULL "
            "ORDER BY due_ts IS NULL, due_ts, id", user_id)

    async def tasks_between(self, user_id: int, start: int, end: int):
        return await self._all(
            "SELECT * FROM tasks WHERE user_id=? AND due_ts>=? AND due_ts<? ORDER BY due_ts",
            user_id, start, end)

    async def overdue(self, user_id: int, before: int):
        return await self._all(
            "SELECT * FROM tasks WHERE user_id=? AND done_ts IS NULL AND due_ts<? ORDER BY due_ts",
            user_id, before)

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
