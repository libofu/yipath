"""Sun sign from a date. Boundaries use the common fixed dates (MVP)."""

from __future__ import annotations

from datetime import date

# (sign, start month, start day), ordered from Capricorn's second half onward.
# A date belongs to the last entry whose (month, day) is <= the date.
_SIGNS = [
    ("摩羯座", 1, 1),
    ("水瓶座", 1, 20),
    ("双鱼座", 2, 19),
    ("白羊座", 3, 21),
    ("金牛座", 4, 20),
    ("双子座", 5, 21),
    ("巨蟹座", 6, 21),
    ("狮子座", 7, 23),
    ("处女座", 8, 23),
    ("天秤座", 9, 23),
    ("天蝎座", 10, 23),
    ("射手座", 11, 22),
    ("摩羯座", 12, 22),
]


def sun_sign(d: date) -> str:
    result = _SIGNS[0][0]
    for name, m, day in _SIGNS:
        if (d.month, d.day) >= (m, day):
            result = name
    return result


def sign_season(d: date) -> str:
    """The sign the sun is in on date d (the 'season' for that day)."""
    return sun_sign(d)
