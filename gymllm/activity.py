"""Lightweight usage signals for the admin dashboard: who's been seen
recently, and how many workouts were parsed today across every provider.
Both are deliberately cheap -- at most one write per user per day, not per
request. There is no per-request traffic logging in this app."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from .extensions import db
from .models import ParseLog, UserActivity


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def touch(email: str) -> None:
    """Mark `email` as seen today. A no-op write-wise on every request after
    the first one today."""
    day = today()
    row = db.session.get(UserActivity, email)
    if row is None:
        db.session.add(UserActivity(user_email=email, last_active_date=day))
        db.session.commit()
    elif row.last_active_date != day:
        row.last_active_date = day
        db.session.commit()


def active_counts() -> dict:
    day = today()
    week_ago = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
    return {
        "today": UserActivity.query.filter(UserActivity.last_active_date == day).count(),
        "this_week": UserActivity.query.filter(UserActivity.last_active_date >= week_ago).count(),
    }


def record_parse(email: str) -> None:
    """A workout was successfully parsed, with any provider -- separate from
    LLMUsage, which only caps the shared site model."""
    day = today()
    row = ParseLog.query.filter_by(user_email=email, day=day).first()
    if row is None:
        db.session.add(ParseLog(user_email=email, day=day, count=1))
    else:
        row.count += 1
    db.session.commit()


def parses_today() -> int:
    day = today()
    total = (
        db.session.query(func.coalesce(func.sum(ParseLog.count), 0))
        .filter(ParseLog.day == day)
        .scalar()
    )
    return int(total)
