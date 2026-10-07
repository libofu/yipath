"""Quality check for ONE user over many consecutive days: does it stay fresh?

Usage (from backend/):  python scripts/longitudinal.py [profile_index 0-9] [days=14] [YYYY-MM-DD start]
Prints repetition metrics and writes longitudinal_<model>_<version>.md (gitignored).
"""

import re
import sys
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sample_readings import PROFILES  # noqa: E402

from app.advice.prompt import PROMPT_VERSION  # noqa: E402
from app.advice.schema import Profile  # noqa: E402
from app.advice.service import AdviceService, make_llm  # noqa: E402
from app.main import _load_dotenv  # noqa: E402
from app.store import Store  # noqa: E402

NAMES = {"work": "宜·事业", "life": "宜·起居", "avoid": "忌"}
NGRAM = 8  # characters; a repeated 8-char run across days reads as a stock phrase


def main() -> None:
    _load_dotenv()
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    start = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2026, 10, 7)

    llm = make_llm()
    model = getattr(llm, "_model", "unknown")
    plans: list[dict[str, str]] = []

    class Spy:
        def complete(self, system: str, user: str) -> str:
            plans.append(dict(re.findall(r"- (宜·事业|宜·起居|忌)｜(.+?)：", user)))
            return llm.complete(system, user)

    svc = AdviceService(Store(Path(tempfile.mkdtemp()) / "s.sqlite3"), Spy())
    bd, hr, mbti = PROFILES[idx]
    profile = Profile(birth_date=bd, birth_hour=hr, mbti=mbti)
    uid, _ = svc.store.create_user(profile)

    readings, lines = [], [f"# profile #{idx + 1} {bd} hour={hr} {mbti}, {days} days from {start}", ""]
    for i in range(days):
        d = start + timedelta(days=i)
        r = svc.get(uid, profile, "today", d)
        readings.append(r)
        lines += [f"## {d} **{r.theme}**"] + [
            f"- {NAMES[k]}｜{plans[i][NAMES[k]]}：{getattr(r, k).action}（{getattr(r, k).reason}）" for k in NAMES
        ] + [""]
        print(f"day {i + 1}/{days}", flush=True)
    out = Path(__file__).resolve().parent.parent / f"longitudinal_{model}_{PROMPT_VERSION}.md"
    out.write_text("\n".join(lines), encoding="utf-8")

    # ---- metrics ----
    themes = [r.theme for r in readings]
    print(f"\nmodel={model} {PROMPT_VERSION} profile #{idx + 1}, {days} days -> {out.name}")
    print(f"distinct themes: {len(set(themes))}/{days}; same theme on consecutive days: "
          f"{sum(a == b for a, b in zip(themes, themes[1:]))}")
    for k, name in NAMES.items():
        labels = [p[name] for p in plans]
        same_next = sum(a == b for a, b in zip(labels, labels[1:]))
        texts = [getattr(r, k).action for r in readings]
        grams = Counter()
        for t in texts:
            grams.update({t[j : j + NGRAM] for j in range(len(t) - NGRAM + 1)})
        stock = [(g, n) for g, n in grams.most_common(40) if n >= 3][:3]
        print(f"{name}: angles used {len(set(labels))}, same angle on consecutive days {same_next}; "
              f"{NGRAM}-char runs repeated on 3+ days: {len([1 for g, n in grams.items() if n >= 3])}  top {stock}")
    phrases = Counter(p for r in readings for p in ["容我细看", "容我思量", "且缓一缓", "改日再议", "先记下", "待我斟酌",
                                                     "容我想想", "稍后答复", "容我理一理", "今日不便，明日再议"]
                      if p in r.avoid.action + r.work.action + r.life.action)
    print("reply phrases:", dict(phrases))


if __name__ == "__main__":
    main()
