"""استخراج توکن‌های درون‌متنی یک کار: #دسته !اولویت ~تخمین @مسئول *تکرار."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import dates
from .db import DEFAULT_CATEGORY

PRIORITY_WORDS = {"فوری": 1, "مهم": 2, "عادی": 3, "1": 1, "2": 2, "3": 3}
RECUR_WORDS = {"روزانه": "daily", "هفتگی": "weekly", "ماهانه": "monthly",
               "daily": "daily", "weekly": "weekly", "monthly": "monthly"}

_TAG = re.compile(r"(?<!\S)#([^\s#]+)")
_PRI = re.compile(r"(?<!\S)!(فوری|مهم|عادی|[123])(?!\S)")
_EST = re.compile(r"(?<!\S)~(\d+(?:\.\d+)?)\s*(ساعت|س|h|دقیقه|د|m)?(?![\w؀-ۿ])")
_MENTION = re.compile(r"(?<!\S)@([\w.\-\u0600-\u06FF]+)")
_RECUR = re.compile(r"(?<!\S)\*(روزانه|هفتگی|ماهانه|daily|weekly|monthly)(?!\S)")


@dataclass
class Inline:
    title: str
    category: str | None = None
    priority: int = 3
    est_min: int | None = None
    mentions: list[str] = field(default_factory=list)
    recur: str | None = None


def clean_category(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.replace("_", " ").replace("‌", " ").strip(" :：-–—")).strip() \
        or DEFAULT_CATEGORY


def parse_inline(text: str) -> Inline:
    t = dates.normalize(text)
    out = Inline(title="")

    m = _TAG.search(t)
    if m:
        out.category = clean_category(m[1])
    t = _TAG.sub(" ", t)

    m = _PRI.search(t)
    if m:
        out.priority = PRIORITY_WORDS[m[1]]
    t = _PRI.sub(" ", t)

    m = _EST.search(t)
    if m:
        unit = m[2] or "m"
        minutes = float(m[1]) * (60 if unit in ("ساعت", "س", "h") else 1)
        out.est_min = max(1, round(minutes))
    t = _EST.sub(" ", t)

    out.mentions = _MENTION.findall(t)
    t = _MENTION.sub(" ", t)

    m = _RECUR.search(t)
    if m:
        out.recur = RECUR_WORDS[m[1]]
    t = _RECUR.sub(" ", t)

    out.title = re.sub(r"\s+", " ", t).strip(" -–—:،,")
    return out
