"""Changing one logged workout: its lifts and cardio, its name, its date, and the
day's weigh-in. The logic the day edit page and the JSON API share. Nothing here
knows about forms, redirects or JSON; a refusal is an EditError carrying a code and
the message to show."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import preferences, session_meta, sessions, social
from .exercises import match_exercise
from .extensions import db
from .logflow import FUTURE_DATE, bodyweight_text, lift_weight, save_bodyweight
from .models import BodyWeight, Cardio, Workout
from .parsing import clean_duration, is_iso_date

LIFT_FIELDS = ("exercise", "weight", "sets", "reps", "notes")
CARDIO_FIELDS = ("activity", "distance", "duration", "notes")
# (editable fields, the field that may never be blanked) for lifts, then cardio.
ROWS = ((LIFT_FIELDS, "exercise"), (CARDIO_FIELDS, "activity"))

BAD_DATE = "Pick a valid date. No changes were saved."
WEIGH_IN_TAKEN = (
    "You already weighed in on that day. Clear one of the two readings first. "
    "No changes were saved."
)


class EditError(Exception):
    """Why an edit was refused: a stable `code` and the message to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Edit:
    """What to change. Rows are keyed by id: a dict of the fields to set (already
    stripped), or None to delete the row. New rows are already through
    normalize_entry / normalize_cardio."""

    date: str = ""  # blank keeps the date
    title: str | None = None  # None leaves the name alone
    visibility: str | None = None  # None leaves it alone
    bodyweight: str | None = None  # None leaves the weigh-in alone, "" clears it
    lifts: dict[int, dict | None] = field(default_factory=dict)
    cardio: dict[int, dict | None] = field(default_factory=dict)
    new_lifts: list[dict] = field(default_factory=list)
    new_cardio: list[dict] = field(default_factory=list)


@dataclass
class Result:
    date: str
    session: int
    removed: bool  # no lifts or cardio are left in this workout
    weigh_in_left: bool  # ...but the weigh-in edited with it still is


def records(user_email: str, when: str, n: int):
    """One session's lifts and cardio (in log order) and the day's weigh-in, as models."""
    lifts = (
        Workout.query.filter_by(user_email=user_email, date=when, session=n)
        .order_by(Workout.id)
        .all()
    )
    cardio = (
        Cardio.query.filter_by(user_email=user_email, date=when, session=n)
        .order_by(Cardio.id)
        .all()
    )
    weight = BodyWeight.query.filter_by(user_email=user_email, date=when).first()
    return lifts, cardio, weight


def other_sessions(user_email: str, when: str, n: int) -> list[int]:
    """The day's other sessions' numbers."""
    rows, cardio = sessions.all_rows(user_email), sessions.all_cardio(user_email)
    return [k for k in sessions.session_numbers(rows, cardio).get(when, []) if k != n]


def is_first(others: list[int], n: int) -> bool:
    """The day's weigh-in is edited along with the day's first workout."""
    return not others or n < min(others)


def apply(user_email: str, when: str, n: int, today: date, edit: Edit) -> Result:
    """Make the edit and commit it. Nothing is saved when it is refused."""
    try:
        return _apply(user_email, when, n, today, edit)
    except EditError:
        db.session.rollback()
        raise


def _apply(user_email: str, when: str, n: int, today: date, edit: Edit) -> Result:
    new_date = edit.date.strip() or when
    if not is_iso_date(new_date):
        raise EditError("bad_date", BAD_DATE)
    moving = new_date != when
    if moving and date.fromisoformat(new_date) > today:
        raise EditError("future_date", FUTURE_DATE)
    unit = preferences.get_weight_unit(user_email)
    lifts, cardio, weight = records(user_email, when, n)
    others = other_sessions(user_email, when, n)
    # The weigh-in is the day's, not a workout's: it travels with this workout only
    # when nothing else is left on the old day.
    handles_weight = is_first(others, n)
    weight_moves = moving and not others
    if not handles_weight:
        bodyweight = ""
    elif edit.bodyweight is None:
        bodyweight = weight.weight if weight else ""
    else:
        try:
            bodyweight = bodyweight_text(edit.bodyweight, unit)
        except ValueError as e:
            raise EditError("bad_bodyweight", str(e)) from None
    if (
        moving
        and weight_moves
        and bodyweight
        and BodyWeight.query.filter_by(user_email=user_email, date=new_date).first() is not None
    ):
        raise EditError("weigh_in_taken", WEIGH_IN_TAKEN)
    new_n = sessions.next_session(user_email, new_date) if moving else n

    def weighed(value: str) -> str:
        try:
            return lift_weight(value, unit)
        except ValueError as e:
            raise EditError("bad_weight", str(e)) from None

    kept = 0
    for found, changes, (fields, required) in zip(
        (lifts, cardio), (edit.lifts, edit.cardio), ROWS, strict=True
    ):
        for row in found:
            change = changes.get(row.id, {})
            if change is None:
                db.session.delete(row)
                continue
            kept += 1
            for name in fields:
                if name not in change:
                    continue
                value = change[name]
                if name == required and not value:
                    continue  # never blank the name itself
                if required == "exercise" and name == "weight":
                    value = weighed(value)
                elif name == "duration":
                    value = clean_duration(value)
                if (getattr(row, name) or "") != value:
                    setattr(row, name, value)
                    if name == "exercise":  # a renamed lift gets its new muscle groups
                        match = match_exercise(value)
                        row.tags = match[1] if match else ""
            row.date, row.session = new_date, new_n

    for entry in edit.new_lifts:
        entry = {f: entry[f] for f in LIFT_FIELDS}
        entry["weight"] = weighed(entry["weight"])
        match = match_exercise(entry["exercise"])
        if match:
            entry["exercise"], tags = match
        else:
            tags = ""
        db.session.add(
            Workout(user_email=user_email, date=new_date, session=new_n, tags=tags, **entry)
        )
        kept += 1
    for c in edit.new_cardio:
        c = {f: c[f] for f in CARDIO_FIELDS}
        c["duration"] = clean_duration(c["duration"])
        db.session.add(Cardio(user_email=user_email, date=new_date, session=new_n, **c))
        kept += 1

    if handles_weight:
        if weight is not None and not bodyweight:
            db.session.delete(weight)
            weight = None
        elif weight is not None:
            weight.weight = bodyweight
            if weight_moves:
                weight.date = new_date
        elif bodyweight:
            weight = save_bodyweight(user_email, when if not weight_moves else new_date, bodyweight)

    if not kept:
        session_meta.clear_session(user_email, when, n)
        weigh_in_left = weight is not None and handles_weight
        if not weigh_in_left and not others:  # nothing is left on the day
            session_meta.clear_day_visibility(user_email, when)
        db.session.commit()
        return Result(new_date, new_n, removed=True, weigh_in_left=weigh_in_left)

    if moving:
        session_meta.move_session(user_email, when, n, new_date, new_n)
        session_meta.move_reactions(user_email, when, n, new_date, new_n)
        if not others:
            session_meta.clear_day_visibility(user_email, when)
    # A blank title doesn't wipe the moved name.
    if edit.title is not None and (edit.title.strip() or not moving):
        session_meta.set_title(user_email, new_date, new_n, edit.title)
    if edit.visibility is not None:
        social.set_visibility(user_email, new_date, social.clean_visibility(edit.visibility))
    db.session.commit()
    return Result(new_date, new_n, removed=False, weigh_in_left=False)
