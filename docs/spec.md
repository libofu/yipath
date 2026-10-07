# yipath (易行) — Product Spec (MVP)

## Product
An iOS subscription app for people tired of making decisions. A calm coach reads the user's Bazi chart against today's and this week's pillars, adds zodiac and MBTI context, and says what to do and how.

- **Name:** yipath / 易行 (follow the Book of Changes; make action easier)
- **Language:** Chinese UI and content
- **Tone:** a calm fortune-teller with a light classical (文言) flavor, in the spirit of the almanac's 宜/忌. Steady and concrete, never fear-based; classical wording is seasoning, meaning stays plain.
- **Platform:** iOS first (SwiftUI, iOS 17+)
- **Monetization:** subscription

## Systems (MVP)
| System | Role |
|---|---|
| Bazi | Natal chart compared with the day pillar (today) and week pillars (this week). Drives the daily/weekly variation. |
| Zodiac | Sun sign from birth date, plus current sign season. |
| MBTI | User-picked. Shapes phrasing and pacing of advice, not divination. |

Deferred: Plum Blossom / I Ching, blood type, month and year readings.

## Output (per period: today, week)
- `theme`: a four-character idiom/phrase or one line of classical verse (4-10 chars, no punctuation), e.g. 木气补身, 风物长宜放眼量
- `work` (宜·事业), `life` (宜·起居), `avoid` (忌): each has `action` (concrete, doable, <=50 chars) and `reason` (one classical-flavored line, <=40 chars)

## Principles
- Code computes charts (deterministic, tested). The LLM only interprets.
- Everyday decisions only. No medical, financial, or legal directives. No fear language.
- App carries an entertainment/reflection disclaimer.

## Out of scope for v1
Android, mainland China compliance (ICP, fortune-telling content rules), history/journaling, widgets.
