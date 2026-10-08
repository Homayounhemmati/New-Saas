"""شبیه‌سازی کامل گفتگو با ربات بدون شبکه (Bot با session جعلی)."""
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from planner_bot import handlers
from planner_bot.db import DB


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[str] = []

    async def close(self): ...
    async def stream_content(self, *a, **k): ...

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        text = getattr(method, "text", None)
        if text:
            self.sent.append(text)
        return Message(message_id=1, date=datetime.now(), chat=Chat(id=1, type="private"),
                       text=text or "")


def test_category_and_import_flow(tmp_path):
    async def go():
        handlers.db = DB(str(tmp_path / "t.db"))
        await handlers.db.open()
        session = FakeSession()
        bot = Bot("1:TEST", session=session)
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(handlers.router)
        user, chat = User(id=7, is_bot=False, first_name="x"), Chat(id=7, type="private")
        n = 0

        async def say(text):
            nonlocal n
            n += 1
            session.sent.clear()
            ent = []
            if text.startswith("/"):
                ent = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            msg = Message.model_validate({"message_id": n, "date": datetime.now(), "chat": chat,
                                          "from": user, "text": text, "entities": ent})
            await dp.feed_update(bot, Update(update_id=n, message=msg))
            return "\n".join(session.sent)

        async def press(data):
            nonlocal n
            n += 1
            session.sent.clear()
            msg = Message(message_id=99, date=datetime.now(), chat=chat, text="x")
            cb = CallbackQuery(id="1", from_user=user, chat_instance="c", data=data, message=msg)
            await dp.feed_update(bot, Update(update_id=n, callback_query=cb))
            return "\n".join(session.sent)

        try:
            out = await say("/add دویدن #ورزش | فردا 07:00")
            assert "ورزش" in out and "ثبت شد" in out
            await say("/cat ورزش 💪")
            assert "💪 ورزش — 1 کار باز" in await say("/cats")
            assert "دویدن" in await say("/week ورزش")
            assert "دویدن" not in await say("/week کار")

            await say("/import")
            md = "## شنبه\n- 07:00 ورزش #ورزش\n- 09:00 جلسه #کار\n## یکشنبه\n- مطالعه #شخصی"
            out = await say(md)
            assert "3 کار پیدا شد" in out
            out = await press("imp:ok")
            assert "3 کار ثبت شد" in out
            await say("/import")
            await say(md)
            assert "3 مورد تکراری" in await press("imp:ok")
            assert "آمار شما" in await say("/stats")
            assert "مطالعه" in await say("/all شخصی")
            assert "ورزش" not in await say("/all شخصی")
        finally:
            await handlers.db.close()
    asyncio.run(go())
