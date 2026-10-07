"""Prompt construction. Bump PROMPT_VERSION whenever wording changes so cached
readings written by an older prompt are not served."""

from __future__ import annotations

from datetime import date

from app.calc.bazi import NatalChart
from app.calc.bazi_daily import DayReading, WeekReading
from app.calc.zodiac import sign_season, sun_sign

from .schema import Profile

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """你是「易行」(yipath) 的教练。用户已经厌倦了不断做决定，希望你替他们理清今天或这一周「做什么、怎么做」，让他们把精力放在更重要的事情上。

语气：冷静、稳定、简洁的教练口吻，像一个可靠的朋友。用「你」称呼用户。不渲染焦虑，不用吓人的措辞，不下绝对的断言，用「适合」「倾向于」「更顺」这类说法。

你会收到由程序精确计算好的八字、星座、MBTI 与当日/当周信息。不要自己重新排盘，也不要编造未提供的信息，只基于所给内容解读。

十神含义（相对用户日主）：比肩=自立与同伴；劫财=竞争与分享；食神=表达与创作；伤官=突破与挑剔；偏财=机会与社交；正财=稳健与积累；七杀=压力与挑战；正官=规则与责任；偏印=独处与钻研；正印=学习与被支持。
冲=变动、打断、节奏被打乱；合=顺畅、牵绊、容易达成一致。
日干五行若是命盘偏弱的五行，视为「补充」的日子；若是命盘偏旺的五行，宜收敛节奏。

MBTI 只用来决定建议的说法与节奏（例如 I 型多安排独处恢复，J 型给出明确步骤），不当作命理依据。

安全边界：只给日常工作与生活的安排建议。不给医疗、投资理财、法律方面的指令；不预言疾病、事故、生死。涉及这些话题时，建议改为「放慢、核对、咨询专业人士」。

输出要求：
- 只输出一个 JSON 对象，不要任何其他文字、不要代码块标记。
- 字段：theme（一句话主题，≤30字）、work、life、avoid；每个都是 {"action": ..., "reason": ...}。
- action 必须具体、可执行、最好带时间段或时长（如「上午先花40分钟处理最难的一件事」），≤60字。
- reason 一句话，说明依据（可引用十神、五行、冲合、星座或 MBTI），≤60字。
- avoid 是今天/本周最该避开的一件事，同样给具体做法。
- 全部使用简体中文。"""


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
    bits = [f"{r.day.isoformat()} 日柱{r.pillar.text}", f"十神{r.ten_god}", f"日干五行{r.element}"]
    if r.element_is_weak:
        bits.append("补命盘偏弱五行")
    if r.he:
        bits.append("合" + "/".join(r.he))
    if r.chong:
        bits.append("冲" + "/".join(r.chong))
    return "，".join(bits)


def build_today_prompt(profile: Profile, chart: NatalChart, reading: DayReading) -> str:
    lines = _chart_lines(chart) + _profile_lines(profile, reading.day)
    lines += [
        f"今天：{reading.day.isoformat()}",
        f"流年{reading.year_pillar.text} 流月{reading.month_pillar.text}",
        _day_line(reading),
        "请为用户生成「今日」建议。",
    ]
    return "\n".join(lines)


def build_week_prompt(profile: Profile, chart: NatalChart, week: WeekReading) -> str:
    lines = _chart_lines(chart) + _profile_lines(profile, week.start)
    lines.append(f"本周：{week.days[0].day.isoformat()} 至 {week.days[-1].day.isoformat()}（周一至周日）")
    lines += [_day_line(r) for r in week.days]
    lines.append("本周十神分布：" + " ".join(f"{k}{v}" for k, v in week.ten_god_counts().items()))
    if week.harmony_days():
        lines.append("顺畅的日子：" + "、".join(r.day.isoformat() for r in week.harmony_days()))
    if week.clash_days():
        lines.append("容易被打乱的日子：" + "、".join(r.day.isoformat() for r in week.clash_days()))
    lines.append("请为用户生成「本周」建议，action 里可以指明具体星期几。")
    return "\n".join(lines)
