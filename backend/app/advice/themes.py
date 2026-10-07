"""Theme library: real idioms / verse lines chosen by code, not invented by the model.

The model is only asked to pick one of a few candidates that fit the day's chart
(see data/themes.txt for the entries and their tags). Selection is deterministic
for a given seed, so the same user/period always gets the same candidates, and
different days rotate.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.calc.bazi_daily import DayReading, WeekReading

DATA_FILE = Path(__file__).resolve().parent / "data" / "themes.txt"

TEN_GODS = {"比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印"}
ELEMENT_TAGS = {"木", "火", "土", "金", "水"}
RELATION_TAGS = {"冲", "合"}
KNOWN_TAGS = TEN_GODS | ELEMENT_TAGS | RELATION_TAGS

# How much each kind of match counts when ranking entries for a day/week.
_W_GOD, _W_RELATION, _W_ELEMENT = 3, 2, 1


@dataclass(frozen=True)
class Entry:
    text: str
    tags: frozenset[str]
    source: str


@dataclass(frozen=True)
class ThemeContext:
    god: str            # ten god of the day (or the week's dominant one)
    element: str        # element of the day stem (or the week's dominant one)
    chong: bool = False
    he: bool = False


@lru_cache(maxsize=1)
def load_entries() -> tuple[Entry, ...]:
    entries = []
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        text, tags, source = line.split("|")
        entries.append(Entry(text, frozenset(tags.split()), source))
    return tuple(entries)


def context_for_day(r: DayReading) -> ThemeContext:
    return ThemeContext(god=r.ten_god, element=r.element, chong=bool(r.chong), he=bool(r.he))


def _dominant(values: list[str]) -> str:
    """Most frequent value; on a tie, the one that appears first."""
    counts = Counter(values)
    return max(counts, key=lambda v: (counts[v], -values.index(v)))


def context_for_week(w: WeekReading) -> ThemeContext:
    """The week's dominant ten god / element; a clash or combination only counts when
    at least two days have it, so one stray 冲 doesn't set the tone of the week."""
    return ThemeContext(
        god=_dominant([r.ten_god for r in w.days]),
        element=_dominant([r.element for r in w.days]),
        chong=len(w.clash_days()) >= 2,
        he=len(w.harmony_days()) >= 2,
    )


def _score(entry: Entry, ctx: ThemeContext) -> int:
    s = 0
    if ctx.god in entry.tags:
        s += _W_GOD
    if ctx.element in entry.tags:
        s += _W_ELEMENT
    if ctx.chong and "冲" in entry.tags:
        s += _W_RELATION
    if ctx.he and "合" in entry.tags:
        s += _W_RELATION
    return s


def _tiebreak(seed: str, text: str) -> str:
    return hashlib.sha256(f"{seed}|{text}".encode()).hexdigest()


POOL_SIZE = 12  # how many best-fitting entries compete for the n candidate slots


def pick_candidates(ctx: ThemeContext, seed: str, n: int = 5) -> list[str]:
    """n distinct entries that fit the context, rotating with `seed`.

    The POOL_SIZE best-fitting entries (ties broken by seed) form a pool, and the seed
    then decides which n of them are offered, so the same context on another day shows
    different candidates. If too few entries match, general fallbacks fill the pool.
    """
    ranked = sorted(load_entries(), key=lambda e: (-_score(e, ctx), _tiebreak(seed, e.text)))
    pool = ranked[: max(POOL_SIZE, n)]
    return [e.text for e in sorted(pool, key=lambda e: _tiebreak(seed, "pick|" + e.text))[:n]]


# --- reply phrases -------------------------------------------------------------------
# One phrase per reading, chosen by code, so the model can't settle on a single stock line.
REPLY_PHRASES = [
    "容我细看", "容我思量", "且缓一缓", "改日再议", "先记下",
    "待我斟酌", "容我想想", "稍后答复", "容我理一理", "今日不便，明日再议",
]


def pick_reply_phrase(seed: str) -> str:
    return min(REPLY_PHRASES, key=lambda p: _tiebreak(seed, p))
