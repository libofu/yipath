# yipath (易行)

iOS subscription app: a calm-coach daily/weekly guide based on Bazi, zodiac and MBTI. See `docs/spec.md`.

## Layout
- `backend/` Python 3.12, FastAPI. `app/calc/` deterministic chart math, `app/advice/` prompt + LLM service.
- `ios/` SwiftUI app (iOS 17+).
- `docs/` spec and copy.

## Rules
- Chart calculation must stay deterministic and covered by pytest fixtures. The LLM never computes charts.
- The LLM API key lives only on the backend (`.env`, never committed).
- All user-facing content is Chinese; voice is a calm fortune-teller with light classical flavor (宜/忌), no fear-based language, no medical/financial/legal directives. Themes come only from the curated library `backend/app/advice/data/themes.txt` (`text|tags|source`); never let the model invent one. Add entries only with a verifiable source. Card angles/time slots come from `backend/app/advice/data/angles.txt`; do not put concrete example sentences in the system prompt (the model copies them into nearly every reading). After any prompt change, bump `PROMPT_VERSION` and run `python scripts/sample_readings.py`.
- The owner is a Swift beginner: keep iOS code simple and commented where the SwiftUI idiom is non-obvious.
- Git identity for this repo is `libofu`; remote uses the SSH alias `github-libofu`. Do not change global git config.

## iOS app (ios/)
- SwiftUI, iOS 17+, bundle id `com.libofu.yipath`. The Xcode project is generated from `ios/project.yml` with XcodeGen (`brew install xcodegen`, then `cd ios && xcodegen`); do not commit `Yipath.xcodeproj` or `Info.plist`.
- Backend URL is `YIPATH_API_BASE_URL` in `project.yml` (default `http://127.0.0.1:8000`, simulator + local uvicorn).
- Debug-only launch arguments: `-yipath-demo` (skip onboarding with a sample profile), `-yipath-tab N` (open tab 0/1/2).
- No Chinese serif font ships with iOS (Songti/Kaiti are absent), so text renders in PingFang. A real almanac look needs a bundled font such as Noto Serif SC.

## Commands
- Backend tests: `cd backend && python -m pytest`
- Backend dev server: `cd backend && uvicorn app.main:app --reload`
- iOS build: `cd ios && xcodegen && xcodebuild -project Yipath.xcodeproj -scheme Yipath -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath build build`
- iOS tests: same command with `test` instead of `build`
- Prompt quality checks (real model calls): `cd backend && python scripts/sample_readings.py` (20 readings) and `python scripts/longitudinal.py 0 14` (one user, 14 days)
