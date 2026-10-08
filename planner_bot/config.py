from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Tehran"))
DB_PATH = os.getenv("DB_PATH", "planner.db")
DEFAULT_MORNING = "08:00"
DEFAULT_EVENING = "21:00"
