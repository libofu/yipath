"""Natal Bazi chart (four pillars) built on lunar-python.

Everything here is deterministic. The LLM never computes any of this.
MVP simplifications: no true-solar-time correction, and the library's default
handling of the 23:00-24:00 hour (late Zi) is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lunar_python import Solar

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"

GAN_ELEMENT = dict(zip(GAN, "木木火火土土金金水水"))
ZHI_ELEMENT = dict(zip(ZHI, "水土木木土火火土金金土水"))
ELEMENTS = "木火土金水"

# Even index in GAN is yang (甲丙戊庚壬), odd is yin.
_PRODUCES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
_CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


def is_yang(gan: str) -> bool:
    return GAN.index(gan) % 2 == 0


def ten_god(day_master: str, other: str) -> str:
    """十神 of stem `other` relative to the day master stem."""
    me, you = GAN_ELEMENT[day_master], GAN_ELEMENT[other]
    same = is_yang(day_master) == is_yang(other)
    if me == you:
        return "比肩" if same else "劫财"
    if _PRODUCES[me] == you:
        return "食神" if same else "伤官"
    if _CONTROLS[me] == you:
        return "偏财" if same else "正财"
    if _CONTROLS[you] == me:
        return "七杀" if same else "正官"
    return "偏印" if same else "正印"  # you produce me


@dataclass(frozen=True)
class Pillar:
    gan: str
    zhi: str

    @property
    def text(self) -> str:
        return self.gan + self.zhi


@dataclass(frozen=True)
class NatalChart:
    year: Pillar
    month: Pillar
    day: Pillar
    hour: Pillar | None  # None when birth time is unknown

    @property
    def day_master(self) -> str:
        return self.day.gan

    @property
    def day_master_element(self) -> str:
        return GAN_ELEMENT[self.day.gan]

    @property
    def pillars(self) -> list[Pillar]:
        return [p for p in (self.year, self.month, self.day, self.hour) if p]

    def element_counts(self) -> dict[str, int]:
        """Count of each element across all stems and branches."""
        counts = {e: 0 for e in ELEMENTS}
        for p in self.pillars:
            counts[GAN_ELEMENT[p.gan]] += 1
            counts[ZHI_ELEMENT[p.zhi]] += 1
        return counts

    def weakest_elements(self) -> list[str]:
        counts = self.element_counts()
        low = min(counts.values())
        return [e for e in ELEMENTS if counts[e] == low]

    def strongest_elements(self) -> list[str]:
        counts = self.element_counts()
        high = max(counts.values())
        return [e for e in ELEMENTS if counts[e] == high]


def _pillar(text: str) -> Pillar:
    return Pillar(text[0], text[1])


def natal_chart(
    birth_date: date, birth_hour: int | None = None, birth_minute: int = 0
) -> NatalChart:
    """Build the natal chart. Pass birth_hour=None if the time is unknown.

    Year and month pillars switch on solar terms (立春, 节), not Jan 1 or the
    lunar new year; lunar-python handles that.
    """
    hour = 12 if birth_hour is None else birth_hour
    solar = Solar.fromYmdHms(birth_date.year, birth_date.month, birth_date.day, hour, birth_minute, 0)
    ec = solar.getLunar().getEightChar()
    return NatalChart(
        year=_pillar(ec.getYear()),
        month=_pillar(ec.getMonth()),
        day=_pillar(ec.getDay()),
        hour=None if birth_hour is None else _pillar(ec.getTime()),
    )
