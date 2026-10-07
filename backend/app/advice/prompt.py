"""Prompt construction. Bump PROMPT_VERSION whenever wording changes so cached
readings written by an older prompt are not served."""

from __future__ import annotations

from datetime import date

from app.calc.bazi import NatalChart
from app.calc.bazi_daily import DayReading, WeekReading
from app.calc.zodiac import sign_season, sun_sign

from .schema import Profile

PROMPT_VERSION = "v4"

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
- theme：一个四字成语/四字短语，或一句有确切出处的古诗词名句，4～10 字，不带标点与出处署名。拿不准出处时，用四字成语。取褒义或中性之意，勿用暗含警告、败象的（如「木秀于林」）。
  主题要贴合当日的十神与五行之象，每次各异，勿总用「张弛有度」「欣欣向荣」「行稳致远」「顺时而动」这类万能成语；契合时优先用古诗词名句，如「长风破浪会有时」「行到水穷处」「风物长宜放眼量」「春风得意马蹄疾」「会当凌绝顶」，这些仅供参考，不必照抄。要贴合当日/当周的主旨。
- work（宜·事业）、life（宜·起居）、avoid（忌）：各为 {"action": ..., "reason": ...}。
- action：具体、可执行，最好带时段或时长，≤50 字，语气带一点文言（如「晨起先办最难一事，四十分钟不接外扰」）。
- reason：一句话点明依据，≤40 字，文言短句，可引一个命理词（十神/五行/冲合/星座/MBTI），其余用白话让人看得懂。
- 「忌」不必都教人如何回话；若要给应对之语，每次换不同的说法（如「容我细看」「且缓一缓」「改日再议」「先记下」），同一份读数里最多出现一次，也不必每份都带。
- 三条要各不相同：不要三条都落在「独处散步」或「不接新任务」上；每次从不同角度出发。
- 时段随命盘与当日气象而定，不必按晨、午、夜的固定顺序，忌那一条也不必总在入夜。
- 提到星期几时，以输入里每日行首标注的「周X」为准，不要自己推算。
- 前后一致：某一天若在 work 或 life 中被推荐，就不要在 avoid 中又劝人避开。
- 全部使用简体中文。

示范（仅示范格式与语气，内容勿照抄）：
{"theme":"静水流深","work":{"action":"晨起先办最难一事，四十分钟不接外扰","reason":"食神当令，文思易出，宜趁清晨吐秀"},"life":{"action":"日暮后与旧友通一次电话，十分钟即可","reason":"木气偏弱，得人气滋养方能舒展"},"avoid":{"action":"午后勿当场应承他人新托付，先记下，隔一时辰再答","reason":"日支逢冲，节奏易乱，急应反多返工"}}"""


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
