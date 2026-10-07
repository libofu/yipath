# Deploying the backend

The backend is one small Python service (FastAPI) plus one SQLite file. The setup below runs it
on a single small server with Docker, and gets an HTTPS certificate automatically.

```
iPhone app ──https──▶ Caddy (port 443) ──▶ yipath backend (port 8000, inside Docker) ──▶ /data/yipath.sqlite3
Apple servers ──https──▶ /apple/notifications (the same address)
```

## What you need
- A small Linux server with a public IP (1 vCPU / 1 GB RAM is plenty; the work is waiting on the AI provider, not computing).
- A domain name, e.g. `api.example.com`, with an **A record** pointing at the server's IP.
- Ports **80 and 443** open to the internet (80 is used to obtain the certificate).
- Docker and the Compose plugin on the server.
- Your AI provider key (`DEEPSEEK_API_KEY`, or `ANTHROPIC_API_KEY`).

## First deployment
```bash
# on the server
git clone git@github.com:libofu/yipath.git /opt/yipath      # or copy the repo there
cd /opt/yipath/deploy
cp .env.production.example .env.production
nano .env.production                                          # fill in the key, check the other values
YIPATH_DOMAIN=api.example.com docker compose up -d --build
```
To avoid typing the domain each time, put `YIPATH_DOMAIN=api.example.com` in a file named `.env` in
the `deploy/` folder (Compose reads it automatically; it is git-ignored).

Check that it works:
```bash
curl https://api.example.com/health          # {"status":"ok"}
docker compose ps                            # app should say "healthy" after ~30 s
docker compose logs app --tail 30
```

### It refuses to start? That is on purpose
In production the server checks its setup at boot and stops with a clear message instead of failing
on the first customer. Read it with `docker compose logs app`.

| Message | Fix |
|---|---|
| `DEEPSEEK_API_KEY is not set` / `ANTHROPIC_API_KEY is not set` | add the key to `.env.production` |
| `YIPATH_LLM='x' is not a known provider` | use `deepseek` or `anthropic` |
| `database folder /data does not exist` / `is not writable` | the `yipath-data` volume is missing or has wrong permissions (see "Volumes" below) |
| `Apple root certificate check failed` | `backend/app/data/AppleRootCA-G3.cer` was changed; restore it from git |
| `YIPATH_PRODUCT_IDS is empty` | remove the variable (defaults apply) or list your product ids |

## Connect the app and Apple
1. **App:** in `ios/project.yml` set `YIPATH_API_BASE_URL: "https://api.example.com"`, then `cd ios && xcodegen` and rebuild.
2. **Apple:** in App Store Connect, App Information > App Store Server Notifications, set both the
   Production and Sandbox URL to `https://api.example.com/apple/notifications` and choose Version 2.
   Use "Request a test notification"; the server answers `{"handled": false}` for Apple's TEST message.

## Updating
```bash
cd /opt/yipath && git pull
cd deploy && docker compose up -d --build        # data lives in the volume, so it survives
```

## Backups (do this before real users arrive)
The database is a single file, so losing the server means losing every account unless it is backed up.
```bash
# take a backup now (consistent even while the server is running); keeps the newest 14
docker compose exec -T app python scripts/backup_db.py --keep 14

# schedule it daily at 03:15 (crontab -e on the server)
15 3 * * * cd /opt/yipath/deploy && docker compose exec -T app python scripts/backup_db.py --keep 14

# copy the backups off the server (a backup on the same disk does not survive the disk)
docker compose cp app:/data/backups ./backups-copy
```
Backups land in `/data/backups` on the volume. Also turn on your hosting provider's disk snapshots if it offers them.

### Restoring
```bash
docker compose stop app
docker compose run --rm --no-deps -T app sh -c 'cp /data/backups/yipath-YYYYmmdd-HHMMSS.sqlite3 /data/yipath.sqlite3'
docker compose start app
```

## Volumes
- `yipath-data` holds the database and backups. **Never delete it** (`docker compose down -v` does).
- `caddy-data` holds the HTTPS certificates; losing it only means they are re-issued.

## Design notes
- **One worker, one server.** The database is a SQLite file, so run exactly one backend container. This is
  fine for thousands of users because requests are short and the slow part (writing a reading, 5-35 s) waits on
  the AI provider without holding a database lock. If you ever outgrow it, the next step is moving to
  PostgreSQL, not adding workers.
- **Readings are cached** per user and day (or week), so each user costs about one AI call per day plus one per week.
- **Secrets** live only in `deploy/.env.production` on the server (git-ignored). The image contains none.
- **The container runs as an unprivileged user,** and only Caddy is reachable from the internet.
- **Logs** are plain Docker logs: `docker compose logs -f app`. They contain request lines, not login tokens.

## What has and has not been checked
Checked (see `backend/tests/test_deploy.py` and a manual run): the startup checks and their messages, the
production behaviour (anonymous signup off, forged sign-in and webhooks rejected), the backup and prune logic,
and that the app starts from a clean environment holding only `requirements.lock` and the `app/` + `scripts/`
folders, exactly as the image is laid out.

**Not checked:** `docker build` and `docker compose up` themselves, because Docker was not available where this
was written. Expect to fix small things on first run (a typo, a permission), and see the messages above.
Also unchecked: the HTTPS certificate step (needs your real domain) and anything involving Apple's live servers
(see `docs/launch-checklist.md`).

## Other hosting
Any host that runs a container works (Fly.io, Railway, a VPS...). Keep the same rules: one instance, a
persistent volume mounted at `/data`, the variables from `deploy/.env.production.example`, HTTPS in front.
Pick a region close to your users that can also reach the AI provider's API and Apple's servers. Hosting inside
mainland China brings extra requirements (ICP filing) that are out of scope for this version.
