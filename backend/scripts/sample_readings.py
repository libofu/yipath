"""Quality check: generate real readings for sample profiles and print them.

Usage (from backend/):  python scripts/sample_readings.py [YYYY-MM-DD]
Uses whichever provider YIPATH_LLM / the .env keys select. Writes
scratch output to samples_out_<model>_<prompt version>.md (gitignored).
"""

import re
import sys
import tempfile
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.advice.schema import Profile  # noqa: E402
from app.advice.prompt import PROMPT_VERSION  # noqa: E402
from app.advice.service import AdviceService, make_llm  # noqa: E402
from app.main import _load_dotenv  # noqa: E402
from app.store import Store  # noqa: E402

PROFILES = [
    (date(1990, 5, 17), 14, "INFJ"),
    (date(1985, 11, 2), 6, "ENTJ"),
    (date(1995, 3, 21), None, "ISFP"),
    (date(2000, 1, 1), 12, "ENFP"),
    (date(1978, 8, 8), 23, "ISTJ"),
    (date(1992, 12, 22), 3, None),
    (date(1988, 2, 4), 18, "INTP"),
    (date(2003, 7, 15), 9, "ESFJ"),
    (date(1982, 9, 30), None, "ENTP"),
    (date(1998, 6, 6), 21, "ISTP"),
]


def main() -> None:
    _load_dotenv()
    on = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 10, 7)
    llm = make_llm()
    model = getattr(llm, "_model", "unknown")
    out = Path(__file__).resolve().parent.parent / f"samples_out_{model}_{PROMPT_VERSION}.md"
    cards_meta = []  # (hint, slot) per card, in call order, to measure echoing afterwards

    class Spy:
        def complete(self, system: str, user: str) -> str:
            cards_meta.append(re.findall(r"- (?:宜·事业|宜·起居|忌)｜.+?：(.+?)｜时段：(\S+)", user))
            return llm.complete(system, user)

    svc = AdviceService(Store(Path(tempfile.mkdtemp()) / "s.sqlite3"), Spy())
    lines = []
    readings = []
    for i, (bd, hr, mbti) in enumerate(PROFILES, 1):
        p = Profile(birth_date=bd, birth_hour=hr, mbti=mbti)
        uid, _ = svc.store.create_user(p)
        for period in ("today", "week"):
            r = svc.get(uid, p, period, on)
            readings.append(r)
            lines += [
                f"## #{i} {bd} hour={hr} {mbti} — {period}",
                f"**{r.theme}**",
                f"- 工作：{r.work.action}（{r.work.reason}）",
                f"- 生活：{r.life.action}（{r.life.reason}）",
                f"- 避免：{r.avoid.action}（{r.avoid.reason}）",
                "",
            ]
        print(f"done #{i}", flush=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {out}")

    # echo check: does a card repeat >= 8 consecutive characters of its angle hint?
    echoed = slot_ok = total = 0
    for r, meta in zip(readings, cards_meta):
        for card, (hint, slot) in zip((r.work, r.life, r.avoid), meta):
            total += 1
            slot_ok += slot in card.action
            echoed += SequenceMatcher(None, card.action, hint).find_longest_match(0, len(card.action), 0, len(hint)).size >= 8
    print(f"{total} cards | time slot used: {slot_ok} | echoing the angle hint (>=8 chars): {echoed}")


if __name__ == "__main__":
    main()
