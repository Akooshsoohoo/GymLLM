"""Parsing a described workout and saving a reviewed one: the logic the HTML routes
and the JSON API share. Nothing here knows about forms, redirects or JSON; a refusal
is a LogError carrying a code and the message to show."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from flask import current_app

from . import activity, preferences, quota, session_meta, sessions, social
from .exercises import llm_tags, match_exercise
from .extensions import db
from .llm.client import BadOutputError, LLMError, RateLimitError
from .llm.providers import LLMConfig
from .models import BodyWeight, Cardio, Workout
from .parsing import (
    ParsedWorkout,
    clean_bodyweight,
    clean_duration,
    clean_lift_weight,
    is_iso_date,
)

MAX_ENTRIES = 100
MAX_SITE_TAG_CALLS = 10  # per save, so tagging cannot drain the shared allowance

BAD_LIFT_WEIGHT = (
    "“{}” isn’t a weight. Use a number, like 185 lbs, or bodyweight. Nothing was saved."
)
BAD_BODY_WEIGHT = "“{}” isn’t a body weight. Use a number, like 160 lbs. Nothing was saved."
FUTURE_DATE = "That date hasn’t happened yet. Nothing was saved."
BAD_DATE = "Date must be in YYYY-MM-DD format."
NOTHING_TO_SAVE = "Nothing to save: every row was empty or deleted."

QUOTA_EXCEEDED = "quota_exceeded"
RATE_LIMITED = "rate_limited"
BAD_OUTPUT = "bad_output"
MODEL_ERROR = "model_error"


class LogError(Exception):
    """Why a parse or a save was refused: a stable `code` and the message to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def site_limit() -> int:
    return int((LLMConfig.site_settings() or {}).get("daily_limit", 0))


def lift_weight(value: str, unit: str) -> str:
    """clean_lift_weight(), with the message to show when the value is refused."""
    try:
        return clean_lift_weight(value, unit)
    except ValueError as e:
        raise ValueError(BAD_LIFT_WEIGHT.format(e)) from None


def bodyweight_text(value: str | None, unit: str) -> str:
    try:
        return clean_bodyweight(value, unit)
    except ValueError as e:
        raise ValueError(BAD_BODY_WEIGHT.format(e)) from None


def save_bodyweight(user_email: str, when: str, weight: str) -> BodyWeight:
    """One reading per day: a second weigh-in on the same date replaces the first."""
    reading = BodyWeight.query.filter_by(user_email=user_email, date=when).first()
    if reading is None:
        reading = BodyWeight(user_email=user_email, date=when, weight=weight, notes="")
        db.session.add(reading)
    else:
        reading.weight = weight
    return reading


def parse(user_email: str, config: LLMConfig, run: Callable[[], ParsedWorkout]) -> ParsedWorkout:
    """Spend one free log (shared model only), make the model call with `run`, and
    give the log back if the model delivered nothing."""
    if config.is_site:
        limit = site_limit()
        if not quota.consume(user_email, limit):
            raise LogError(
                QUOTA_EXCEEDED,
                f"You've used today's {limit} free logs. Come back tomorrow, add this "
                "one manually, or set up your own model in Settings for unlimited logging.",
            )

    def failed(code: str, message: str) -> LogError:
        """The model gave nothing back, so the free log isn't spent."""
        if config.is_site:
            quota.refund(user_email)
        return LogError(code, message)

    try:
        parsed = run()
    except RateLimitError as e:
        message = e.user_message
        if config.is_site:
            message = (
                "The shared model is busy or its daily allowance is used up. Try again in a "
                "minute, or use your own key on the Settings page."
            )
        raise failed(RATE_LIMITED, message) from None
    except LLMError as e:
        code = BAD_OUTPUT if isinstance(e, BadOutputError) else MODEL_ERROR
        raise failed(code, e.user_message) from None
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Unexpected error while parsing workout")
        raise failed(
            MODEL_ERROR, "Something went wrong while talking to the model. Please try again."
        ) from None
    activity.record_parse(user_email)
    return parsed


def save(
    user_email: str,
    when: str,
    today: date,
    entries: list[dict],
    cardio: list[dict],
    bodyweight: str | None,
    *,
    visibility: str | None = None,
    title: str | None = None,
    get_client: Callable[[], object | None] | None = None,
    tag_calls: int = MAX_ENTRIES,
    in_browser: bool = False,
) -> int:
    """Save reviewed entries (already through normalize_entry / normalize_cardio) as a
    new workout on `when`, and return its session number. `get_client` supplies the
    model that tags unknown exercises, at most `tag_calls` times; `in_browser` means
    the page already tagged them."""
    if not is_iso_date(when):
        raise LogError("bad_date", BAD_DATE)
    if date.fromisoformat(when) > today:
        raise LogError("future_date", FUTURE_DATE)
    unit = preferences.get_weight_unit(user_email)
    try:
        for entry in entries:
            entry["weight"] = lift_weight(entry["weight"], unit)
    except ValueError as e:
        raise LogError("bad_weight", str(e)) from None
    try:
        bodyweight = bodyweight_text(bodyweight, unit)
    except ValueError as e:
        raise LogError("bad_bodyweight", str(e)) from None
    for c in cardio:
        c["duration"] = clean_duration(c["duration"])
    if not (entries or cardio or bodyweight):
        raise LogError("nothing_to_save", NOTHING_TO_SAVE)

    client = get_client() if get_client else None
    # Every save is its own workout: a second log on the same day is a second card.
    n = sessions.next_session(user_email, when)
    for entry in entries:
        match = match_exercise(entry["exercise"])
        if match:
            name, tags = match
        elif in_browser:
            name = entry["exercise"]
            tags = entry.get("tags", "")  # tagged by the local model in the browser
        else:
            name = entry["exercise"]
            tags = ""
            if client and tag_calls > 0:
                tag_calls -= 1
                tags = llm_tags(name, client)
        db.session.add(
            Workout(
                user_email=user_email,
                date=when,
                session=n,
                exercise=name,
                weight=entry["weight"],
                sets=entry["sets"],
                reps=entry["reps"],
                notes=entry["notes"],
                tags=tags,
            )
        )
    db.session.add_all(
        Cardio(
            user_email=user_email,
            date=when,
            session=n,
            activity=c["activity"],
            distance=c["distance"],
            duration=c["duration"],
            notes=c["notes"],
        )
        for c in cardio
    )
    if entries or cardio:
        # Covers the whole day, so a later save that day can change it.
        social.set_visibility(user_email, when, social.clean_visibility(visibility))
        session_meta.set_title(user_email, when, n, title)
    if bodyweight:
        save_bodyweight(user_email, when, bodyweight)  # always private
    db.session.commit()
    return n
