from datetime import date

from app.advice.angles import KINDS, SLOTS, load_angles, pick_card_plans
from app.advice.prompt import SYSTEM_PROMPT, build_today_prompt, build_week_prompt
from app.advice.schema import Profile
from app.advice.themes import KNOWN_TAGS, ThemeContext
from app.calc.bazi import natal_chart
from app.calc.bazi_daily import day_reading, week_reading

BANNED_IN_HINTS = ["财", "钱", "签约", "投资", "借贷", "买卖", "健康", "病", "医"]


def test_angle_file_is_valid():
    angles = load_angles()
    assert {a.kind for a in angles} == set(KINDS)
    for kind, minimum in [("work", 6), ("life", 5), ("avoid", 8)]:
        assert sum(a.kind == kind for a in angles) >= minimum, kind
    labels = [(a.kind, a.label) for a in angles]
    assert len(set(labels)) == len(labels)
    for a in angles:
        assert a.tags <= KNOWN_TAGS, (a.label, a.tags - KNOWN_TAGS)
        assert a.hint
        # safety boundary: no money / contract / health topics in what we ask the model to write
        assert not any(w in a.hint for w in BANNED_IN_HINTS), a.hint


def test_plans_deterministic_with_distinct_slots():
    ctx = ThemeContext("七杀", "木", chong=True)
    a = pick_card_plans(ctx, "1:today:2026-10-07")
    assert a == pick_card_plans(ctx, "1:today:2026-10-07")
    assert set(a) == set(KINDS)
    slots = [p.slot for p in a.values()]
    assert len(set(slots)) == 3 and set(slots) <= set(SLOTS)


def test_angles_rotate_across_days():
    ctx = ThemeContext("食神", "木")
    seen = {k: set() for k in KINDS}
    seen_slots = {k: set() for k in KINDS}
    for d in range(1, 29):
        for k, p in pick_card_plans(ctx, f"1:today:2026-10-{d:02d}").items():
            seen[k].add(p.label)
            seen_slots[k].add(p.slot)
    assert all(len(v) >= 3 for v in seen.values()), seen
    # no card is stuck on one time of day (the old "晨起 for everything" problem)
    assert all(len(v) >= 3 for v in seen_slots.values()), seen_slots


def test_clash_days_prefer_clash_suited_avoid_angles():
    # 正财 has no avoid-angle of its own, so the day's 冲 is the only signal.
    by_label = {(a.kind, a.label): a for a in load_angles()}

    def clash_rate(ctx):
        hits = 0
        for d in range(1, 29):
            plan = pick_card_plans(ctx, f"1:today:d{d}")["avoid"]
            hits += "冲" in by_label[("avoid", plan.label)].tags
        return hits

    assert clash_rate(ThemeContext("正财", "土", chong=True)) == 28
    assert clash_rate(ThemeContext("正财", "土", chong=False)) < 28


def test_prompts_carry_the_card_plans():
    profile = Profile(birth_date=date(2000, 1, 1), birth_hour=12)
    chart = natal_chart(profile.birth_date, profile.birth_hour)
    plans = pick_card_plans(ThemeContext("七杀", "木"), "s")
    t = build_today_prompt(profile, chart, day_reading(chart, date(2026, 10, 7)), None, None, plans)
    w = build_week_prompt(profile, chart, week_reading(chart, date(2026, 10, 7)), None, None, plans)
    for text in (t, w):
        assert "三条各自的角度与时段" in text
        assert "宜·事业｜" in text and "宜·起居｜" in text and "忌｜" in text
        assert f"时段：{plans['work'].slot}" in text


def test_system_prompt_no_longer_contains_copyable_examples():
    # these exact phrases were being copied into almost every reading
    for magnet in ["四十分钟不接外扰", "勿当场应承", "隔一时辰再答", "独处散步", "静水流深"]:
        assert magnet not in SYSTEM_PROMPT, magnet
    assert "角度" in SYSTEM_PROMPT


def test_slots_respect_angle_restrictions():
    angles = {(a.kind, a.label): a for a in load_angles()}
    restricted = [a for a in angles.values() if a.slots != frozenset(SLOTS)]
    assert any(a.label == "收心" for a in restricted)
    violations = 0
    for d in range(1, 120):
        for ctx in (ThemeContext("七杀", "木", chong=True), ThemeContext("正财", "水", he=True), ThemeContext("偏印", "土")):
            plans = pick_card_plans(ctx, f"{d}:today:x")
            assert len({p.slot for p in plans.values()}) == 3
            for kind, plan in plans.items():
                violations += plan.slot not in angles[(kind, plan.label)].slots
    assert violations == 0


def test_system_prompt_tells_model_to_paraphrase_angles():
    assert "不要照抄" in SYSTEM_PROMPT
