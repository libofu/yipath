# yipath (易行)

iOS subscription app: a calm-coach daily/weekly guide based on Bazi, zodiac and MBTI. See `docs/spec.md`.

## Layout
- `backend/` Python 3.12, FastAPI. `app/calc/` deterministic chart math, `app/advice/` prompt + LLM service.
- `ios/` SwiftUI app (iOS 17+).
- `docs/` spec and copy.

## Rules
- Chart calculation must stay deterministic and covered by pytest fixtures. The LLM never computes charts.
- The LLM API key lives only on the backend (`.env`, never committed).
- All user-facing content is Chinese; tone is a calm coach, no fear-based language, no medical/financial/legal directives.
- The owner is a Swift beginner: keep iOS code simple and commented where the SwiftUI idiom is non-obvious.
- Git identity for this repo is `libofu`; remote uses the SSH alias `github-libofu`. Do not change global git config.

## Commands
- Backend tests: `cd backend && python -m pytest`
- Backend dev server: `cd backend && uvicorn app.main:app --reload`
