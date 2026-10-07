import json
from collections import Counter
from datetime import date

import pytest

from app.advice.prompt import SYSTEM_PROMPT, build_today_prompt, build_week_prompt
from app.advice.schema import Profile, Reading
from app.advice.service import AdviceService
from app.advice.themes import (
    KNOWN_TAGS,
    REPLY_PHRASES,
    ThemeContext,
    context_for_day,
    context_for_week,
    load_entries,
    pick_candidates,
    pick_reply_phrase,
)
from app.calc.bazi import natal_chart
from app.calc.bazi_daily import day_reading, week_reading
from app.store import Store

CARD = {"action": "晨起先办最难一事", "reason": "食神当令，宜趁早吐秀"}


# --- the data file -----------------------------------------------------------------------

def test_library_is_large_unique_and_valid():
    entries = load_entries()
    texts = [e.text for e in entries]
    assert len(entries) >= 150
    assert len(set(texts)) == len(texts), [t for t, n in Counter(texts).items() if n > 1]
    for e in entries:
        # every entry must satisfy the same rule the API enforces on the model's theme
        Reading(theme=e.text, work=CARD, life=CARD, avoid=CARD)
        assert e.tags <= KNOWN_TAGS, (e.text, e.tags - KNOWN_TAGS)
        assert e.source


def test_every_ten_god_and_element_and_relation_has_enough_entries():
    entries = load_entries()
    for tag in ["比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印"]:
        assert sum(tag in e.tags for e in entries) >= 8, tag
    for tag in ["木", "火", "土", "金", "水"]:
        assert sum(tag in e.tags for e in entries) >= 8, tag
    assert sum("冲" in e.tags for e in entries) >= 10
    assert sum("合" in e.tags for e in entries) >= 8
    assert sum(not e.tags for e in entries) >= 5  # general fallbacks exist


# --- picking -------------------------------------------------------------------------------

def test_candidates_are_deterministic_distinct_and_n_long():
    ctx = ThemeContext("七杀", "木", chong=True)
    a = pick_candidates(ctx, "1:today:2026-10-07")
    assert a == pick_candidates(ctx, "1:today:2026-10-07")
    assert len(a) == 5 and len(set(a)) == 5


def test_candidates_fit_the_context():
    entries = {e.text: e for e in load_entries()}
    for god in ["七杀", "食神", "正官", "偏印", "劫财"]:
        picks = pick_candidates(ThemeContext(god, "金"), "s")
        assert sum(god in entries[t].tags for t in picks) >= 3, (god, picks)
    clash = pick_candidates(ThemeContext("比肩", "土", chong=True), "s")
    assert any("冲" in entries[t].tags for t in clash)
    combo = pick_candidates(ThemeContext("比肩", "土", he=True), "s")
    assert any("合" in entries[t].tags for t in combo)


def test_same_context_rotates_across_days():
    ctx = ThemeContext("七杀", "木")
    seen = set()
    for d in range(1, 29):
        seen |= set(pick_candidates(ctx, f"1:today:2026-10-{d:02d}"))
    assert len(seen) >= 15


def test_different_users_get_different_candidates():
    ctx = ThemeContext("食神", "木")
    assert pick_candidates(ctx, "1:today:2026-10-07") != pick_candidates(ctx, "2:today:2026-10-07")


def test_context_for_day_and_week():
    chart = natal_chart(date(2000, 1, 1), 12)  # branches 卯 子 午 午
    d = day_reading(chart, date(2026, 10, 7))  # 甲寅
    assert context_for_day(d) == ThemeContext(god=d.ten_god, element="木", chong=False, he=False)
    w = week_reading(chart, date(2026, 10, 7))  # Mon 子 clashes 午, Sun 午 clashes 子
    ctx = context_for_week(w)
    assert ctx.chong is True
    assert ctx.god in w.ten_god_counts() and ctx.element in w.element_counts()


def test_reply_phrase_deterministic_and_varied():
    assert pick_reply_phrase("a") == pick_reply_phrase("a")
    assert pick_reply_phrase("a") in REPLY_PHRASES
    assert len({pick_reply_phrase(f"1:today:{i}") for i in range(60)}) >= 6


# --- prompt + service integration --------------------------------------------------------------

@pytest.fixture
def profile():
    return Profile(birth_date=date(2000, 1, 1), birth_hour=12, mbti="ENFP")


def test_prompts_include_candidates_and_phrase(profile):
    chart = natal_chart(profile.birth_date, profile.birth_hour)
    t = build_today_prompt(profile, chart, day_reading(chart, date(2026, 10, 7)), ["甲乙丙丁", "戊己庚辛"], "且缓一缓")
    assert "主题候选" in t and "甲乙丙丁｜戊己庚辛" in t and "「且缓一缓」" in t
    w = build_week_prompt(profile, chart, week_reading(chart, date(2026, 10, 7)), ["甲乙丙丁"], "先记下")
    assert "主题候选" in w and "「先记下」" in w


def test_system_prompt_requires_choosing_a_candidate():
    assert "主题候选" in SYSTEM_PROMPT and "原文照抄" in SYSTEM_PROMPT


class Llm:
    def __init__(self, theme_fn):
        self.theme_fn, self.prompts = theme_fn, []

    def complete(self, system, user):
        self.prompts.append(user)
        cands = user.split("主题候选（theme 须从中择一，原文照抄）：")[1].splitlines()[0].split("｜")
        return json.dumps({"theme": self.theme_fn(cands), "work": CARD, "life": CARD, "avoid": CARD}, ensure_ascii=False)


def test_service_sends_candidates_and_keeps_a_valid_choice(tmp_path, profile):
    store = Store(tmp_path / "t.sqlite3")
    llm = Llm(lambda c: c[2])
    uid, _ = store.create_user(profile)
    r = AdviceService(store, llm).get(uid, profile, "today", date(2026, 10, 7))
    assert r.theme in llm.prompts[0] and r.theme in pick_candidates(
        context_for_day(day_reading(natal_chart(profile.birth_date, profile.birth_hour), date(2026, 10, 7))),
        f"{uid}:today:2026-10-07",
    )


@pytest.mark.parametrize("invented", ["自创的主题啊", "长风破浪"])
def test_service_replaces_invented_theme_with_a_candidate(tmp_path, profile, invented):
    store = Store(tmp_path / "t.sqlite3")
    llm = Llm(lambda c: invented)
    uid, _ = store.create_user(profile)
    r = AdviceService(store, llm).get(uid, profile, "today", date(2026, 10, 7))
    assert r.theme != invented
    assert r.theme in {e.text for e in load_entries()}
    assert len(llm.prompts) == 1  # no extra LLM call for the fix
