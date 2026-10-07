# yipath (易行) — Product Spec (MVP)

## Product
An iOS subscription app for people tired of making decisions. A calm coach reads the user's Bazi chart against today's and this week's pillars, adds zodiac and MBTI context, and says what to do and how.

- **Name:** yipath / 易行 (follow the Book of Changes; make action easier)
- **Language:** Chinese UI and content
- **Tone:** calm coach. Steady, concrete, never fear-based.
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
- `theme`: one short line
- `work`, `life`, `avoid`: each has `action` (concrete, doable) and `reason` (one line)

## Principles
- Code computes charts (deterministic, tested). The LLM only interprets.
- Everyday decisions only. No medical, financial, or legal directives. No fear language.
- App carries an entertainment/reflection disclaimer.

## Out of scope for v1
Android, mainland China compliance (ICP, fortune-telling content rules), history/journaling, widgets.
