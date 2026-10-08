"""شبیه‌سازی کامل گفتگو با ربات برای دو کاربر، بدون شبکه (Bot با session جعلی)."""
import asyncio
import re
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from planner_bot import ctx, handlers
from planner_bot.db import DB


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[tuple[int, str]] = []

    async def close(self): ...
    async def stream_content(self, *a, **k): ...

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        if isinstance(method, GetMe):
            return User(id=999, is_bot=True, first_name="Planner", username="planner_test_bot")
        text = getattr(method, "text", None)
        chat_id = getattr(method, "chat_id", 0)
        if text:
            self.sent.append((int(chat_id), text))
        return Message(message_id=1, date=datetime.now(), chat=Chat(id=int(chat_id or 1), type="private"),
                       text=text or "")


ALI = User(id=10, is_bot=False, first_name="علی", username="ali")
SARA = User(id=20, is_bot=False, first_name="سارا", username="sara")


def test_personal_team_and_notifications(tmp_path):
    async def go():
        ctx.db = DB(str(tmp_path / "t.db"))
        await ctx.db.open()
        session = FakeSession()
        bot = Bot("1:TEST", session=session)
        dp = Dispatcher(storage=MemoryStorage())
        handlers.setup(dp)
        n = 0

        async def say(user, text):
            nonlocal n
            n += 1
            session.sent.clear()
            ent = []
            if text.startswith("/"):
                ent = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            msg = Message.model_validate({"message_id": n, "date": datetime.now(),
                                          "chat": Chat(id=user.id, type="private"),
                                          "from": user, "text": text, "entities": ent})
            await dp.feed_update(bot, Update(update_id=n, message=msg))
            return {cid: "\n".join(t for c, t in session.sent if c == cid)
                    for cid in {c for c, _ in session.sent}}

        async def press(user, data):
            nonlocal n
            n += 1
            session.sent.clear()
            msg = Message(message_id=99, date=datetime.now(), chat=Chat(id=user.id, type="private"),
                          text="x")
            cb = CallbackQuery(id="1", from_user=user, chat_instance="c", data=data, message=msg)
            await dp.feed_update(bot, Update(update_id=n, callback_query=cb))
            return {cid: "\n".join(t for c, t in session.sent if c == cid)
                    for cid in {c for c, _ in session.sent}}

        try:
            # --- شخصی + دسته ---
            out = await say(ALI, "/add دویدن #ورزش !فوری ~1h | فردا 07:00")
            assert "ثبت شد" in out[10] and "🔴" in out[10] and "ورزش" in out[10]
            await say(ALI, "/cat ورزش 💪")
            assert "💪 ورزش — 1 کار باز" in (await say(ALI, "/cats"))[10]
            assert "دویدن" in (await say(ALI, "/week ورزش"))[10]
            assert "دویدن" not in (await say(ALI, "/week کار"))[10]

            # --- ساخت تیم و دعوت ---
            out = await say(ALI, "/team شرکت")
            code = re.search(r"start=join_(\S+)", out[10])[1]
            out = await say(SARA, f"/start join_{code}")
            assert "پیوستید" in out[20] and "سارا" in out[10]
            assert "سارا" in (await say(ALI, "/members"))[10]

            # --- اساین و اعلان ---
            out = await say(ALI, "/add گزارش فروش #کار @sara !مهم | فردا 09:00")
            assert "سارا" in out[10] and "کار جدید برای شما" in out[20]
            tid = int(re.search(r"#(\d+) ·", out[10])[1])
            assert "گزارش فروش" in (await say(SARA, "/all شرکت"))[20]
            assert "گزارش فروش" not in (await say(ALI, "/today"))[10]
            assert "گزارش فروش" in (await say(ALI, "/board"))[10]

            # --- گردش کار: شروع ← بازبینی (اعلان به سازنده) ← یادداشت ← انجام ---
            await press(SARA, f"start:{tid}")
            assert "در حال انجام" in (await say(ALI, f"/card {tid}"))[10]
            out = await press(SARA, f"next:{tid}")
            assert "بازبینی" in out[10]
            out = await say(SARA, f"/note {tid} پیش‌نویس آماده است")
            assert "پیش‌نویس" in out[10]
            out = await press(SARA, f"done:{tid}")
            assert "انجام داد" in out[10]

            # --- پاس‌دادن و حذف با مجوز ---
            t2 = int(re.search(r"#(\d+) ·", (await say(ALI, "/add مرور قرارداد @sara"))[10])[1])
            out = await say(SARA, f"/pass {t2} @ali")
            assert "پاس داده شد" in out[10]
            assert "فقط سازنده" in (await say(SARA, f"/del {t2}"))[20]
            assert "حذف شد" in (await say(ALI, f"/del {t2}"))[10]

            # --- تکرارشونده ---
            t3 = int(re.search(r"#(\d+) ·", (await say(ALI, "/add ورزش گروهی @sara *روزانه | فردا 07:00"))[10])[1])
            assert "نوبت بعدی" in (await press(SARA, f"done:{t3}"))[20]

            # --- ورود مارک‌داون در فضای تیم ---
            await say(ALI, "/import")
            md = "## شنبه\n- 07:00 تمرین #ورزش\n- 09:00 جلسه #کار @sara\n## یکشنبه\n- مطالعه #شخصی"
            out = await say(ALI, md)
            assert "3 کار پیدا شد" in out[10]
            assert "3 کار ثبت شد" in (await press(ALI, "imp:ok"))[10]
            await say(ALI, "/import")
            await say(ALI, md)
            assert "3 مورد تکراری" in (await press(ALI, "imp:ok"))[10]

            # --- حریم خصوصی فضای شخصی ---
            out = await say(SARA, "/ws")
            personal_id = (await ctx.db.personal_ws(SARA.id))
            await press(SARA, f"ws:{personal_id}")
            sid = int(re.search(r"#(\d+) ·", (await say(SARA, "/add راز شخصی | فردا 8"))[20])[1])
            assert "پیدا نشد" in (await say(ALI, f"/card {sid}"))[10]

            # --- حذف عضو ---
            assert "حذف شدید" in (await say(ALI, "/kick @sara"))[20]
            assert "پیدا نشد" in (await say(SARA, f"/card {t3}"))[20]
            assert "آمار شما" in (await say(ALI, "/stats"))[10]
        finally:
            await ctx.db.close()
    asyncio.run(go())
