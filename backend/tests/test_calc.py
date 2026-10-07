from datetime import date, timedelta

import pytest

from app.calc.bazi import natal_chart, ten_god
from app.calc.bazi_daily import day_reading, week_reading, week_start
from app.calc.zodiac import sun_sign


def texts(chart):
    return [p.text if p else None for p in (chart.year, chart.month, chart.day, chart.hour)]


# --- natal chart -----------------------------------------------------------

def test_known_chart_2000_01_01_noon():
    # 2000-01-01 is a well-known 戊午 day. It falls before 立春, so the year is
    # still 己卯 (1999), and before 小寒, so the month is 丙子.
    chart = natal_chart(date(2000, 1, 1), 12)
    assert texts(chart) == ["己卯", "丙子", "戊午", "戊午"]
    assert chart.day_master == "戊"
    assert chart.day_master_element == "土"


def test_year_switches_at_lichun_not_jan_1():
    assert natal_chart(date(2024, 1, 15), 12).year.text == "癸卯"
    assert natal_chart(date(2024, 2, 3), 12).year.text == "癸卯"  # before 立春 (Feb 4)
    assert natal_chart(date(2024, 2, 5), 12).year.text == "甲辰"


def test_unknown_birth_hour_has_no_hour_pillar():
    chart = natal_chart(date(2000, 1, 1), None)
    assert chart.hour is None
    assert texts(chart)[:3] == ["己卯", "丙子", "戊午"]
    assert len(chart.pillars) == 3


def test_element_counts():
    chart = natal_chart(date(2000, 1, 1), 12)
    assert chart.element_counts() == {"木": 1, "火": 3, "土": 3, "金": 0, "水": 1}
    assert chart.weakest_elements() == ["金"]
    assert chart.strongest_elements() == ["火", "土"]


def test_deterministic():
    assert natal_chart(date(1990, 5, 17), 14, 30) == natal_chart(date(1990, 5, 17), 14, 30)


# --- ten gods ----------------------------------------------------------------

@pytest.mark.parametrize(
    "other,expected",
    [
        ("甲", "比肩"), ("乙", "劫财"), ("丙", "食神"), ("丁", "伤官"), ("戊", "偏财"),
        ("己", "正财"), ("庚", "七杀"), ("辛", "正官"), ("壬", "偏印"), ("癸", "正印"),
    ],
)
def test_ten_god_for_jia_day_master(other, expected):
    assert ten_god("甲", other) == expected


def test_ten_god_matches_library_example():
    # lunar-python reports 庚 as 偏印 for a 壬 day master.
    assert ten_god("壬", "庚") == "偏印"


# --- daily / weekly ------------------------------------------------------------

def test_day_pillars_2026_10_07():
    chart = natal_chart(date(2000, 1, 1), 12)
    r = day_reading(chart, date(2026, 10, 7))
    assert (r.pillar.text, r.month_pillar.text, r.year_pillar.text) == ("甲寅", "丁酉", "丙午")
    assert r.ten_god == ten_god("戊", "甲")
    assert r.element == "木"


def test_clash_and_harmony_with_natal_branches():
    chart = natal_chart(date(2000, 1, 1), 12)  # branches 卯 子 午 午
    d = date(2026, 1, 1)
    seen = {}
    for i in range(24):
        r = day_reading(chart, d + timedelta(days=i))
        seen.setdefault(r.pillar.zhi, r)
    assert seen["子"].chong == ["日支午", "时支午"]
    assert seen["午"].chong == ["月支子"]
    assert seen["丑"].he == ["月支子"]
    assert seen["未"].he == ["日支午", "时支午"]


def test_week_starts_monday_and_has_seven_days():
    chart = natal_chart(date(2000, 1, 1), 12)
    assert week_start(date(2026, 10, 7)) == date(2026, 10, 5)  # Wednesday -> Monday
    w = week_reading(chart, date(2026, 10, 7))
    assert [r.day for r in w.days] == [date(2026, 10, 5) + timedelta(days=i) for i in range(7)]
    assert sum(w.ten_god_counts().values()) == 7
    assert sum(w.element_counts().values()) == 7


# --- zodiac --------------------------------------------------------------------

@pytest.mark.parametrize(
    "d,expected",
    [
        (date(2026, 10, 7), "天秤座"),
        (date(2026, 1, 1), "摩羯座"),
        (date(2026, 1, 19), "摩羯座"),
        (date(2026, 1, 20), "水瓶座"),
        (date(2026, 3, 20), "双鱼座"),
        (date(2026, 3, 21), "白羊座"),
        (date(2026, 12, 21), "射手座"),
        (date(2026, 12, 22), "摩羯座"),
    ],
)
def test_sun_sign(d, expected):
    assert sun_sign(d) == expected
