# yipath backend image.  Build from the backend/ folder:  docker build -t yipath-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Install dependencies first: this layer is reused until requirements.lock changes.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY app ./app
COPY scripts ./scripts

# Run as an unprivileged user. /data is where the SQLite database lives; mount a volume there,
# or the data disappears whenever the container is replaced.
RUN useradd --system --uid 10001 --home-dir /srv --shell /usr/sbin/nologin yipath \
    && mkdir -p /data \
    && chown yipath:yipath /data
USER yipath

ENV YIPATH_ENV=production \
    YIPATH_DB=/data/yipath.sqlite3
VOLUME /data
EXPOSE 8000

# One worker on purpose: the database is a single SQLite file (see docs/deployment.md).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
