"""Rest days: the recurring rules and the days flipped by hand. The logic the
Progress page and the JSON API share. A refusal is a ValueError with the message to
show."""

from __future__ import annotations

from datetime import date

from . import sessions, stats
from .extensions import db
from .models import RestOverride, RestRule

MAX_REST_RULES = 10
REST_INTERVAL_RANGE = (2, 60)


def add_rule(user_email: str, kind: str, *, weekdays=(), interval_days: int = 0, anchor: date):
    """A new rule: fixed weekdays (Monday is 0), or every `interval_days` days counted
    from `anchor`."""
    if RestRule.query.filter_by(owner_email=user_email).count() >= MAX_REST_RULES:
        raise ValueError(f"You can have up to {MAX_REST_RULES} rest rules.")
    if kind == "interval":
        if not REST_INTERVAL_RANGE[0] <= interval_days <= REST_INTERVAL_RANGE[1]:
            raise ValueError("Pick a rest interval between 2 and 60 days.")
        rule = RestRule(
            owner_email=user_email,
            kind="interval",
            interval_days=interval_days,
            anchor_date=anchor.isoformat(),
        )
    else:
        days = sorted({str(d) for d in weekdays} & set("0123456"))
        if not days:
            raise ValueError("Pick at least one weekday.")
        rule = RestRule(owner_email=user_email, kind="weekdays", weekdays=",".join(days))
    db.session.add(rule)
    db.session.commit()
    return rule


def delete_rule(user_email: str, rule_id: int) -> bool:
    rule = RestRule.query.filter_by(id=rule_id, owner_email=user_email).first()
    if rule is None:
        return False
    db.session.delete(rule)
    db.session.commit()
    return True


def set_day(user_email: str, day: date, today: date, wanted: bool | None = None) -> bool:
    """Make one day rest or not by hand, on top of the schedule (flip it when `wanted`
    is None), and return what it now is. A day still to come, or one with anything
    logged, is refused: a logged day is never shown as rest."""
    when = day.isoformat()
    if day > today:
        raise ValueError("That day hasn’t happened yet.")
    rows = sessions.all_rows(user_email) + sessions.all_cardio(user_email)
    if any(r["date"] == when for r in rows + sessions.all_weights(user_email)):
        raise ValueError("You logged something that day, so it isn’t a rest day.")
    rules = sessions.rest_rules(user_email)
    if wanted is None:
        wanted = not stats.is_rest(day, rules, sessions.rest_overrides(user_email))
    row = db.session.get(RestOverride, (user_email, when))
    if wanted == stats.is_rest(day, rules, {}):
        if row:  # back to what the schedule says
            db.session.delete(row)
    elif row:
        row.is_rest = wanted
    else:
        db.session.add(RestOverride(owner_email=user_email, date=when, is_rest=wanted))
    db.session.commit()
    return wanted
