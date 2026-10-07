"""Day and week pillars and how they relate to a natal chart."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from lunar_python import Solar

from .bazi import ELEMENTS, GAN_ELEMENT, NatalChart, Pillar, ten_god

LIU_HE = {frozenset(p) for p in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")}
LIU_CHONG = {frozenset(p) for p in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")}

_PILLAR_NAMES = {"year": "年", "month": "月", "day": "日", "hour": "时"}


@dataclass(frozen=True)
class DayReading:
    day: date
    pillar: Pillar          # the day's own pillar (流日)
    month_pillar: Pillar
    year_pillar: Pillar
    ten_god: str            # day stem relative to the user's day master
    element: str            # element of the day stem
    element_is_weak: bool   # day stem supplies an element the natal chart lacks
    he: list[str] = field(default_factory=list)     # branch combinations with natal pillars
    chong: list[str] = field(default_factory=list)  # branch clashes with natal pillars


def _day_pillars(d: date) -> tuple[Pillar, Pillar, Pillar]:
    lunar = Solar.fromYmd(d.year, d.month, d.day).getLunar()
    to_p = lambda t: Pillar(t[0], t[1])
    return to_p(lunar.getDayInGanZhi()), to_p(lunar.getMonthInGanZhi()), to_p(lunar.getYearInGanZhi())


def day_reading(chart: NatalChart, d: date) -> DayReading:
    day_p, month_p, year_p = _day_pillars(d)
    he, chong = [], []
    named = [("year", chart.year), ("month", chart.month), ("day", chart.day), ("hour", chart.hour)]
    for name, natal in named:
        if natal is None:
            continue
        pair = frozenset((day_p.zhi, natal.zhi))
        label = f"{_PILLAR_NAMES[name]}支{natal.zhi}"
        if pair in LIU_HE:
            he.append(label)
        elif pair in LIU_CHONG:
            chong.append(label)
    element = GAN_ELEMENT[day_p.gan]
    return DayReading(
        day=d,
        pillar=day_p,
        month_pillar=month_p,
        year_pillar=year_p,
        ten_god=ten_god(chart.day_master, day_p.gan),
        element=element,
        element_is_weak=element in chart.weakest_elements(),
        he=he,
        chong=chong,
    )


@dataclass(frozen=True)
class WeekReading:
    start: date
    days: list[DayReading]

    def ten_god_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.days:
            counts[r.ten_god] = counts.get(r.ten_god, 0) + 1
        return counts

    def element_counts(self) -> dict[str, int]:
        counts = {e: 0 for e in ELEMENTS}
        for r in self.days:
            counts[r.element] += 1
        return counts

    def clash_days(self) -> list[DayReading]:
        return [r for r in self.days if r.chong]

    def harmony_days(self) -> list[DayReading]:
        return [r for r in self.days if r.he]


def week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def week_reading(chart: NatalChart, d: date) -> WeekReading:
    start = week_start(d)
    return WeekReading(start=start, days=[day_reading(chart, start + timedelta(days=i)) for i in range(7)])
