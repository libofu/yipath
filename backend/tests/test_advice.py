import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.advice.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_today_prompt, build_week_prompt
from app.advice.schema import Profile
from app.advice.service import AdviceService, ReadingError, parse_reading
from app.calc.bazi import natal_chart
from app.calc.bazi_daily import day_reading, week_reading
from app.main import app, get_service, get_store
from app.store import Store

GOOD = {
    "theme": "先稳后进",
    "work": {"action": "上午先花40分钟处理最难的一件事", "reason": "正官日，适合守规则、做硬骨头"},
    "life": {"action": "晚上散步20分钟再入睡", "reason": "天秤季，需要平衡节奏"},
    "avoid": {"action": "今天不要临时答应新的邀约", "reason": "日支相冲，容易被打乱"},
}


class FakeLlm:
    def __init__(self, *replies: str):
        self.replies = list(replies) or [json.dumps(GOOD, ensure_ascii=False)]
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.sqlite3")


@pytest.fixture
def profile():
    return Profile(birth_date=date(2000, 1, 1), birth_hour=12, mbti="infj")


# --- parsing ---------------------------------------------------------------------

def test_parse_plain_and_fenced_json():
    raw = json.dumps(GOOD, ensure_ascii=False)
    assert parse_reading(raw).theme == "先稳后进"
    assert parse_reading(f"```json\n{raw}\n```").work.action.startswith("上午")
    assert parse_reading(f"好的：\n{raw}\n以上").avoid.reason


@pytest.mark.parametrize("bad", ["not json", "{}", '{"theme": "x"}'])
def test_parse_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_reading(bad)


def _with(**over):
    d = json.loads(json.dumps(GOOD, ensure_ascii=False))
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


@pytest.mark.parametrize("theme", ["静", "这是一个明显太长的主题句子啊啊"])
def test_theme_length_enforced(theme):
    with pytest.raises(ValueError):
        parse_reading(_with(theme=theme))


def test_theme_accepts_idiom_and_verse():
    assert parse_reading(_with(theme="风物长宜放眼量")).theme == "风物长宜放眼量"
    assert parse_reading(_with(theme="木气补身")).theme == "木气补身"


@pytest.mark.parametrize("theme", ["官星临门，木气生发", "静水 流深", "「静水流深」"])
def test_theme_with_punctuation_rejected(theme):
    with pytest.raises(ValueError):
        parse_reading(_with(theme=theme))


def test_week_prompt_labels_weekdays(profile):
    chart = natal_chart(profile.birth_date, profile.birth_hour)
    text = build_week_prompt(profile, chart, week_reading(chart, date(2026, 10, 7)))
    # 2026-10-07 (甲寅) is a Wednesday
    assert "周三 2026-10-07 日柱甲寅" in text
    assert "周一 2026-10-05" in text and "周日 2026-10-11" in text


def test_overlong_card_text_rejected():
    long_card = {"action": "甲" * 66, "reason": "乙"}
    with pytest.raises(ValueError):
        parse_reading(_with(work=long_card))


def test_profile_normalizes_and_validates_mbti():
    assert Profile(birth_date=date(2000, 1, 1), mbti="intj").mbti == "INTJ"
    with pytest.raises(ValueError):
        Profile(birth_date=date(2000, 1, 1), mbti="XXXX")


# --- prompts -----------------------------------------------------------------------

def test_today_prompt_contains_computed_facts(profile):
    chart = natal_chart(profile.birth_date, profile.birth_hour)
    text = build_today_prompt(profile, chart, day_reading(chart, date(2026, 10, 7)))
    for needle in ["己卯", "丙子", "戊午", "日主：戊（土）", "甲寅", "天秤座", "INFJ", "2026-10-07"]:
        assert needle in text


def test_week_prompt_lists_seven_days(profile):
    chart = natal_chart(profile.birth_date, profile.birth_hour)
    text = build_week_prompt(profile, chart, week_reading(chart, date(2026, 10, 7)))
    assert "2026-10-05 至 2026-10-11" in text
    assert text.count("日干五行") == 7  # once per day (the natal line says 日柱 too)


def test_system_prompt_has_safety_boundary():
    assert "医疗" in SYSTEM_PROMPT and "不渲染焦虑" in SYSTEM_PROMPT


def test_system_prompt_forbids_unsupplied_chart_claims_and_stock_phrase():
    assert "不得自行补充" in SYSTEM_PROMPT and "身强身弱" in SYSTEM_PROMPT
    # the stock reply must not be baked into the example, or models copy it every time
    assert SYSTEM_PROMPT.count("容我思量") == 0


def test_system_prompt_voice_and_theme_rules():
    assert "宜" in SYSTEM_PROMPT and "忌" in SYSTEM_PROMPT and "文言" in SYSTEM_PROMPT
    assert "主题候选" in SYSTEM_PROMPT  # theme comes from the code-picked candidates


# --- service ---------------------------------------------------------------------------

def test_cache_avoids_second_llm_call(store, profile):
    llm = FakeLlm()
    svc = AdviceService(store, llm)
    uid, _ = store.create_user(profile)
    a = svc.get(uid, profile, "today", date(2026, 10, 7))
    b = svc.get(uid, profile, "today", date(2026, 10, 7))
    assert a == b and len(llm.calls) == 1
    svc.get(uid, profile, "today", date(2026, 10, 8))  # new day -> new call
    assert len(llm.calls) == 2


def test_week_is_cached_across_days_of_same_week(store, profile):
    llm = FakeLlm()
    svc = AdviceService(store, llm)
    uid, _ = store.create_user(profile)
    svc.get(uid, profile, "week", date(2026, 10, 5))
    svc.get(uid, profile, "week", date(2026, 10, 11))
    assert len(llm.calls) == 1
    svc.get(uid, profile, "week", date(2026, 10, 12))
    assert len(llm.calls) == 2


def test_retries_once_on_invalid_json(store, profile):
    llm = FakeLlm("sorry, no JSON", json.dumps(GOOD, ensure_ascii=False))
    svc = AdviceService(store, llm)
    uid, _ = store.create_user(profile)
    assert svc.get(uid, profile, "today", date(2026, 10, 7)).work.action
    assert len(llm.calls) == 2


def test_gives_up_after_max_attempts_and_does_not_cache(store, profile):
    llm = FakeLlm("nope")
    svc = AdviceService(store, llm)
    uid, _ = store.create_user(profile)
    with pytest.raises(ReadingError):
        svc.get(uid, profile, "today", date(2026, 10, 7))
    assert store.get_reading(uid, "today", "2026-10-07", PROMPT_VERSION) is None


def test_profile_update_invalidates_cache(store, profile):
    llm = FakeLlm()
    svc = AdviceService(store, llm)
    uid, _ = store.create_user(profile)
    svc.get(uid, profile, "today", date(2026, 10, 7))
    new = Profile(birth_date=date(1990, 5, 17), birth_hour=None)
    store.update_profile(uid, new)
    svc.get(uid, new, "today", date(2026, 10, 7))
    assert len(llm.calls) == 2


def test_token_is_stored_hashed(store, profile):
    uid, token = store.create_user(profile)
    assert store.user_by_token(token)[0] == uid
    assert store.user_by_token("wrong") is None
    import sqlite3
    row = sqlite3.connect(store.path).execute("SELECT token_hash FROM users").fetchone()
    assert token not in row[0]


# --- HTTP -----------------------------------------------------------------------------------

@pytest.fixture
def client(store):
    llm = FakeLlm()
    svc = AdviceService(store, llm)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_service] = lambda: svc
    c = TestClient(app)
    c.llm = llm
    yield c
    app.dependency_overrides.clear()


def _signup(client):
    r = client.post("/profile", json={"birth_date": "2000-01-01", "birth_hour": 12, "mbti": "INFJ"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_requires_token(client):
    assert client.get("/reading/today").status_code == 401
    assert client.get("/reading/today", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_today_and_week_endpoints(client):
    h = _signup(client)
    r = client.get("/reading/today", params={"date": "2026-10-07"}, headers=h)
    assert r.status_code == 200 and r.json()["work"]["action"]
    assert client.get("/reading/week", params={"date": "2026-10-07"}, headers=h).status_code == 200
    client.get("/reading/today", params={"date": "2026-10-07"}, headers=h)
    assert len(client.llm.calls) == 2  # today + week; repeat today was cached


def test_invalid_profile_rejected(client):
    assert client.post("/profile", json={"birth_date": "2000-01-01", "mbti": "ZZZZ"}).status_code == 422


def test_llm_failure_returns_502(store):
    svc = AdviceService(store, FakeLlm("garbage"))
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_service] = lambda: svc
    try:
        c = TestClient(app)
        h = _signup(c)
        assert c.get("/reading/today", params={"date": "2026-10-07"}, headers=h).status_code == 502
    finally:
        app.dependency_overrides.clear()


# --- DeepSeek adapter ------------------------------------------------------------------------

def test_deepseek_client_request_and_response_shape():
    import httpx
    from app.advice.service import DeepSeekClient

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD, ensure_ascii=False)}}]})

    client = DeepSeekClient(api_key="k", transport=httpx.MockTransport(handler))
    svc_reading = parse_reading(client.complete("SYS", "USER"))
    assert svc_reading.theme == "先稳后进"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}


def test_make_llm_selection(monkeypatch):
    from app.advice.service import DeepSeekClient, make_llm

    monkeypatch.delenv("YIPATH_LLM", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert isinstance(make_llm(), DeepSeekClient)
    monkeypatch.setenv("YIPATH_LLM", "nope")
    with pytest.raises(RuntimeError):
        make_llm()
