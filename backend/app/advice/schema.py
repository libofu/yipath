from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Profile(BaseModel):
    """What the user tells us at onboarding."""

    birth_date: date
    birth_hour: int | None = Field(default=None, ge=0, le=23)  # None = unknown
    birth_minute: int = Field(default=0, ge=0, le=59)
    mbti: str | None = None

    @field_validator("mbti")
    @classmethod
    def _mbti(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.upper()
        ok = len(v) == 4 and v[0] in "EI" and v[1] in "SN" and v[2] in "TF" and v[3] in "JP"
        if not ok:
            raise ValueError("mbti must look like INFJ")
        return v


class Card(BaseModel):
    action: str = Field(min_length=1, max_length=120)  # concrete, doable
    reason: str = Field(min_length=1, max_length=120)  # one line


class Reading(BaseModel):
    """The LLM's structured answer; also what the API returns."""

    theme: str = Field(min_length=1, max_length=60)
    work: Card
    life: Card
    avoid: Card


Period = Literal["today", "week"]
