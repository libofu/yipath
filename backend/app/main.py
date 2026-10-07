from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from app.advice.schema import Profile, Reading
from app.advice.service import AdviceService, ReadingError, make_llm
from app.store import Store


def _load_dotenv() -> None:
    """Tiny .env loader (KEY=VALUE lines) so we don't need another dependency."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


class ProfileCreated(BaseModel):
    user_id: int
    token: str


_store: Store | None = None
_service: AdviceService | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def get_service() -> AdviceService:
    global _service
    if _service is None:
        _load_dotenv()
        _service = AdviceService(get_store(), make_llm())
    return _service


def current_user(
    authorization: str = Header(default=""), store: Store = Depends(get_store)
) -> tuple[int, Profile]:
    scheme, _, token = authorization.partition(" ")
    user = store.user_by_token(token) if scheme.lower() == "bearer" and token else None
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or missing token")
    return user


def _today_default() -> date:
    # The audience is Chinese-speaking; clients may pass ?date= to override.
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


app = FastAPI(title="yipath")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/profile", response_model=ProfileCreated)
def create_profile(profile: Profile, store: Store = Depends(get_store)) -> ProfileCreated:
    user_id, token = store.create_user(profile)
    return ProfileCreated(user_id=user_id, token=token)


@app.put("/profile", status_code=204)
def update_profile(
    profile: Profile, user=Depends(current_user), store: Store = Depends(get_store)
) -> None:
    store.update_profile(user[0], profile)


def _reading(period: str, on: date | None, user, service: AdviceService) -> Reading:
    user_id, profile = user
    try:
        return service.get(user_id, profile, period, on or _today_default())  # type: ignore[arg-type]
    except ReadingError:
        raise HTTPException(status_code=502, detail="could not generate a reading, please retry")


@app.get("/reading/today", response_model=Reading)
def reading_today(
    date_: date | None = Query(default=None, alias="date"),
    user=Depends(current_user),
    service: AdviceService = Depends(get_service),
) -> Reading:
    return _reading("today", date_, user, service)


@app.get("/reading/week", response_model=Reading)
def reading_week(
    date_: date | None = Query(default=None, alias="date"),
    user=Depends(current_user),
    service: AdviceService = Depends(get_service),
) -> Reading:
    return _reading("week", date_, user, service)
