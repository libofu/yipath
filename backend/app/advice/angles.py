"""Card angles: code decides what each card is about and at which time of day.

Without this the model settles on one template (every work card "晨起先办最难一事",
every avoid card "勿当场应承新托付"). Here, per reading, the code picks one angle per card
from data/angles.txt, preferring angles that suit the day's chart, rotating by seed, and
assigns a distinct time slot to each card.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .themes import ThemeContext, _tiebreak

DATA_FILE = Path(__file__).resolve().parent / "data" / "angles.txt"

KINDS = ("work", "life", "avoid")
SLOTS = ["晨起", "午前", "午后", "日暮", "入夜"]
POOL_SIZE = 4  # best-fitting angles per card that compete for the single slot


@dataclass(frozen=True)
class Angle:
    kind: str
    label: str
    hint: str
    tags: frozenset[str]
    slots: frozenset[str]  # time slots this angle makes sense at (all slots if unrestricted)


@dataclass(frozen=True)
class CardPlan:
    label: str
    hint: str
    slot: str


@lru_cache(maxsize=1)
def load_angles() -> tuple[Angle, ...]:
    angles = []
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kind, label, hint, tags, slots = line.split("|")
        angles.append(Angle(kind, label, hint, frozenset(tags.split()), frozenset(SLOTS if slots == "-" else slots.split())))
    return tuple(angles)


def _score(a: Angle, ctx: ThemeContext) -> int:
    s = 0
    if ctx.god in a.tags:
        s += 3
    if ctx.chong and "冲" in a.tags:
        s += 2
    if ctx.he and "合" in a.tags:
        s += 2
    if ctx.element in a.tags:
        s += 1
    return s


def pick_card_plans(ctx: ThemeContext, seed: str) -> dict[str, CardPlan]:
    """One angle per card plus three distinct time slots, deterministic for `seed`.

    Angles are chosen first; slots are then dealt out so each card gets a slot its angle
    allows (most restricted cards first), falling back to any free slot if none fits.
    """
    chosen: dict[str, Angle] = {}
    for kind in KINDS:
        mine = [a for a in load_angles() if a.kind == kind]
        pool = sorted(mine, key=lambda a: (-_score(a, ctx), _tiebreak(seed, a.label)))[:POOL_SIZE]
        chosen[kind] = min(pool, key=lambda a: _tiebreak(seed, "pick|" + kind + a.label))

    order = sorted(KINDS, key=lambda k: len(chosen[k].slots))  # most restricted first
    free = sorted(SLOTS, key=lambda s: _tiebreak(seed, "slot|" + s))
    plans = {}
    for kind in order:
        angle = chosen[kind]
        slot = next((s for s in free if s in angle.slots), free[0])
        free.remove(slot)
        plans[kind] = CardPlan(angle.label, angle.hint, slot)
    return {kind: plans[kind] for kind in KINDS}
