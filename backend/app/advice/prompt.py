"""Prompt construction. Bump PROMPT_VERSION whenever wording changes so cached
readings written by an older prompt are not served."""

from __future__ import annotations

from datetime import date

from app.calc.bazi import NatalChart
from app.calc.bazi_daily import DayReading, WeekReading
from app.calc.zodiac import sign_season, sun_sign

from .schema import Profile

PROMPT_VERSION = "v7"

WEEKDAYS = "一二三四五六日"  # Monday-first, matches date.weekday()

SYSTEM_PROMPT = """你是「易行」(yipath) 里的一位先生。用户已厌倦事事自己拿主意，想有人替他们看清今日、本周「宜做什么、忌做什么、怎么做」，好把心力留给更要紧的事。

【语气】
沉稳、从容，带一点算命先生的口吻与文言韵味，如老先生翻着黄历娓娓道来。多用「宜」「忌」「不妨」「且」「勿」「方可」这类词，句子短，有节奏。晨起、午后、日暮、入夜可代替上午、下午、傍晚、晚上。
文言只是点缀，要让现代人一眼读懂，不堆砌生僻字，不故弄玄虚。不渲染焦虑，不吓人，不下「大凶」「必有灾」之类的断语，用「宜」「易」「较顺」「不妨」这类说法。用「你」称呼用户。

【依据】
你会收到由程序精确计算好的八字、星座、MBTI 与当日/当周信息。不要自己重新排盘，不编造未提供的信息，只依所给内容解读。
只可引用输入里明列的十神、五行、冲、合、星座与 MBTI；不得自行补充输入没有的命理判断，如刑、害、破、三合、三会、身强身弱、透干、藏干、用神喜忌、格局等。
十神含义（相对用户日主）：比肩=自立与同伴；劫财=竞争与分享；食神=表达与创作；伤官=突破与挑剔；偏财=机会与社交；正财=稳健与积累；七杀=压力与挑战；正官=规则与责任；偏印=独处与钻研；正印=学习与被支持。
冲=变动、打断、节奏被打乱；合=顺畅、牵绊、易达成一致。
日干五行若是命盘偏弱的五行，视为「补益」之日；若是命盘偏旺的五行，宜收敛节奏。
MBTI 只用来决定建议的说法与节奏（例如 I 型多留独处，J 型给明确步骤），不当作命理依据。

【安全边界】
只给日常工作与生活的安排。不给医疗、投资理财、法律方面的指令；action 与 reason 中不提及钱款、财路、签约、投资、借贷、买卖，也不提身体健康、病痛；不预言疾病、事故、生死。

【输出】
只输出一个 JSON 对象，不要其他文字，不要代码块标记。字段：
- theme：必须从输入「主题候选」中择一，原文照抄，不增不改；选与当日气象及你所写三条建议最相合的一句。
- work（宜·事业）、life（宜·起居）、avoid（忌）：各为 {"action": ..., "reason": ...}。
- action：具体、可执行，≤50 字，须围绕输入为该条指定的「角度」与「时段」，写明做什么、做多久；语气带一点文言。角度说明只是方向，请用自己的话写，不要照抄原句，具体做法（去哪里、做哪一件）自行选定。
- reason：一句话点明依据，≤40 字，文言短句，可引一个命理词（十神/五行/冲合/星座/MBTI），其余用白话让人看得懂。
- 「忌」不必都教人如何回话；若需给应对他人的话术，只可用输入给出的「应对用语」，一份读数至多用一次，也可不用。
- 提到星期几时，以输入里每日行首标注的「周X」为准，不要自己推算。
- 前后一致：某一天若在 work 或 life 中被推荐，就不要在 avoid 中又劝人避开。
- 全部使用简体中文。

格式（仅示意，字段内容须自己写）：
{"theme":"（主题候选之一）","work":{"action":"…","reason":"…"},"life":{"action":"…","reason":"…"},"avoid":{"action":"…","reason":"…"}}"""


def _chart_lines(chart: NatalChart) -> list[str]:
    names = ["年柱", "月柱", "日柱", "时柱"]
    pillars = [chart.year, chart.month, chart.day, chart.hour]
    parts = [f"{n}{p.text}" if p else f"{n}未知" for n, p in zip(names, pillars)]
    counts = chart.element_counts()
    return [
        "命盘：" + " ".join(parts),
        f"日主：{chart.day_master}（{chart.day_master_element}）",
        "五行计数：" + " ".join(f"{e}{n}" for e, n in counts.items()),
        f"偏旺：{'、'.join(chart.strongest_elements())}；偏弱：{'、'.join(chart.weakest_elements())}",
    ]


def _profile_lines(profile: Profile, on: date) -> list[str]:
    lines = [f"星座：{sun_sign(profile.birth_date)}；当前星座季：{sign_season(on)}"]
    lines.append(f"MBTI：{profile.mbti}" if profile.mbti else "MBTI：未提供")
    return lines


def _day_line(r: DayReading) -> str:
    bits = [f"周{WEEKDAYS[r.day.weekday()]} {r.day.isoformat()} 日柱{r.pillar.text}", f"十神{r.ten_god}", f"日干五行{r.element}"]
    if r.element_is_weak:
        bits.append("补命盘偏弱五行")
    if r.he:
        bits.append("合" + "/".join(r.he))
    if r.chong:
        bits.append("冲" + "/".join(r.chong))
    return "，".join(bits)


_CARD_NAMES = {"work": "宜·事业", "life": "宜·起居", "avoid": "忌"}


def _choice_lines(themes: list[str] | None, phrase: str | None, plans: dict | None = None) -> list[str]:
    lines = []
    if plans:
        lines.append("三条各自的角度与时段（action 须围绕之，不得更换）：")
        for kind in ("work", "life", "avoid"):
            p = plans[kind]
            lines.append(f"- {_CARD_NAMES[kind]}｜{p.label}：{p.hint}｜时段：{p.slot}")
    if themes:
        lines.append("主题候选（theme 须从中择一，原文照抄）：" + "｜".join(themes))
    if phrase:
        lines.append(f"应对用语（需要时只可用这一句）：「{phrase}」")
    return lines


def build_today_prompt(
    profile: Profile,
    chart: NatalChart,
    reading: DayReading,
    themes: list[str] | None = None,
    phrase: str | None = None,
    plans: dict | None = None,
) -> str:
    lines = _chart_lines(chart) + _profile_lines(profile, reading.day)
    lines += [
        f"今天：{reading.day.isoformat()}",
        f"流年{reading.year_pillar.text} 流月{reading.month_pillar.text}",
        _day_line(reading),
        *_choice_lines(themes, phrase, plans),
        "请为用户生成「今日」建议。",
    ]
    return "\n".join(lines)


def build_week_prompt(
    profile: Profile,
    chart: NatalChart,
    week: WeekReading,
    themes: list[str] | None = None,
    phrase: str | None = None,
    plans: dict | None = None,
) -> str:
    lines = _chart_lines(chart) + _profile_lines(profile, week.start)
    lines.append(f"本周：{week.days[0].day.isoformat()} 至 {week.days[-1].day.isoformat()}（周一至周日）")
    lines += [_day_line(r) for r in week.days]
    lines.append("本周十神分布：" + " ".join(f"{k}{v}" for k, v in week.ten_god_counts().items()))
    if week.harmony_days():
        lines.append("顺畅的日子：" + "、".join(r.day.isoformat() for r in week.harmony_days()))
    if week.clash_days():
        lines.append("容易被打乱的日子：" + "、".join(r.day.isoformat() for r in week.clash_days()))
    lines += _choice_lines(themes, phrase, plans)
    lines.append("请为用户生成「本周」建议，action 里可以指明具体星期几。")
    return "\n".join(lines)
