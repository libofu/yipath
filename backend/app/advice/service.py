"""Builds the context, asks the LLM, validates the JSON, and caches the result."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Protocol

from pydantic import ValidationError

from app.calc.bazi import natal_chart
from app.calc.bazi_daily import day_reading, week_reading, week_start
from app.store import Store

from .prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_today_prompt, build_week_prompt
from .schema import Period, Profile, Reading

DEFAULT_MODEL = "claude-sonnet-5-5"


class LlmClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    """Thin wrapper so the rest of the code (and tests) never touch the SDK."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        import anthropic  # imported lazily so tests don't need a key

        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._model = model or os.environ.get("YIPATH_MODEL", DEFAULT_MODEL)

    def complete(self, system: str, user: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")


class ReadingError(Exception):
    """The model did not return a valid reading after retrying."""


def parse_reading(text: str) -> Reading:
    """Accept bare JSON, tolerating code fences or stray text around the object."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return Reading.model_validate(json.loads(text[start : end + 1]))


class AdviceService:
    def __init__(self, store: Store, llm: LlmClient, max_attempts: int = 2):
        self.store = store
        self.llm = llm
        self.max_attempts = max_attempts

    def get(self, user_id: int, profile: Profile, period: Period, on: date) -> Reading:
        key = on.isoformat() if period == "today" else week_start(on).isoformat()
        cached = self.store.get_reading(user_id, period, key, PROMPT_VERSION)
        if cached:
            return cached

        chart = natal_chart(profile.birth_date, profile.birth_hour, profile.birth_minute)
        if period == "today":
            user_prompt = build_today_prompt(profile, chart, day_reading(chart, on))
        else:
            user_prompt = build_week_prompt(profile, chart, week_reading(chart, on))

        reading = self._ask(user_prompt)
        self.store.put_reading(user_id, period, key, PROMPT_VERSION, reading)
        return reading

    def _ask(self, user_prompt: str) -> Reading:
        last: Exception | None = None
        for _ in range(self.max_attempts):
            raw = self.llm.complete(SYSTEM_PROMPT, user_prompt)
            try:
                return parse_reading(raw)
            except (ValueError, ValidationError) as e:  # json.JSONDecodeError is a ValueError
                last = e
        raise ReadingError(f"invalid reading after {self.max_attempts} attempts: {last}")
