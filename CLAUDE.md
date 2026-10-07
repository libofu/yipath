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

## Accounts and subscription
- Sign in with Apple -> `POST /auth/apple` (`backend/app/auth.py`, nonce required) -> our own session token. `POST /profile` (anonymous) exists only for development and is off when `YIPATH_ENV=production`.
- Everyone gets a server-side free trial (`YIPATH_TRIAL_DAYS`, default 3), then needs a subscription. Readings return 402 otherwise. `GET /subscription` reports the status.
- StoreKit 2 transactions are verified server-side (`backend/app/subscription.py`: Apple's pinned root cert, marker OIDs, ES256 signature, bundle/product checks). Never trust the app about what was bought. Local Xcode StoreKit transactions are accepted only with `YIPATH_STOREKIT_LOCAL=1` (never in production).
- `POST /apple/notifications` is the App Store Server Notifications V2 webhook (renewals, expiry, refunds): no login, trusted only through Apple's signature, held to the same checks as purchases and never accepts Xcode-local transactions.
- `DELETE /account` erases all server data (App Store requirement). See `docs/launch-checklist.md` for the Apple-account steps and known gaps.

## iOS app (ios/)
- SwiftUI, iOS 17+, bundle id `com.libofu.yipath`. The Xcode project is generated from `ios/project.yml` with XcodeGen (`brew install xcodegen`, then `cd ios && xcodegen`); do not commit `Yipath.xcodeproj` or `Info.plist`.
- Backend URL is `YIPATH_API_BASE_URL` in `project.yml` (default `http://127.0.0.1:8000`, simulator + local uvicorn).
- Local purchases: `ios/StoreKit/Yipath.storekit` (placeholder prices) is used by Xcode's Run and by `SKTestSession` in the tests. `simctl launch` does not apply it, so the paywall shows no products there.
- Debug-only launch arguments: `-yipath-demo` (skip onboarding with a sample profile), `-yipath-tab N` (open tab 0/1/2).
- iOS ships no Chinese serif, so `ios/Yipath/Fonts/` bundles Noto Serif SC (Regular + Bold, subsetted to GB2312 + library characters, SIL OFL; see its README). Use `.songti(size, relativeTo:, weight:)` in views. Re-subset the font if theme/angle files gain rare characters.

## Deployment
- `backend/Dockerfile` (image from `requirements.lock`), `deploy/docker-compose.yml` + `Caddyfile` (automatic HTTPS), guide in `docs/deployment.md`. The Docker build itself has never been run (no Docker on the dev machine): the same layout was checked in a clean venv.
- Production (`YIPATH_ENV=production`) runs `app/preflight.py` at startup and refuses to boot when misconfigured. Run exactly one backend instance (SQLite). Back up with `python scripts/backup_db.py`.
- After changing `backend/requirements.txt`, regenerate `requirements.lock` (command in its header).

## Commands
- Backend tests: `cd backend && python -m pytest`
- Backend dev server: `cd backend && uvicorn app.main:app --reload`
- iOS build: `cd ios && xcodegen && xcodebuild -project Yipath.xcodeproj -scheme Yipath -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath build build`
- iOS tests: same command with `test` instead of `build`
- Prompt quality checks (real model calls): `cd backend && python scripts/sample_readings.py` (20 readings) and `python scripts/longitudinal.py 0 14` (one user, 14 days)
