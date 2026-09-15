"""Per-user daily cap on parses made with the site's shared model."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import LLMUsage


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def used(user_email: str, day: str | None = None) -> int:
    row = LLMUsage.query.filter_by(user_email=user_email, day=day or today()).first()
    return row.count if row else 0


def remaining(user_email: str, limit: int) -> int:
    return max(0, limit - used(user_email))


def consume(user_email: str, limit: int) -> bool:
    """Grant one parse if the user is under `limit` today. Safe under concurrency:
    the increment is a conditional UPDATE, and a lost insert race falls back to it."""
    day = today()
    bump = (
        update(LLMUsage)
        .where(LLMUsage.user_email == user_email, LLMUsage.day == day, LLMUsage.count < limit)
        .values(count=LLMUsage.count + 1)
    )
    if db.session.execute(bump).rowcount:
        db.session.commit()
        return True
    if LLMUsage.query.filter_by(user_email=user_email, day=day).first() is not None:
        db.session.rollback()
        return False  # row exists and is at the limit
    if limit < 1:
        return False
    try:
        db.session.add(LLMUsage(user_email=user_email, day=day, count=1))
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()  # someone else inserted first; try the increment once more
        granted = bool(db.session.execute(bump).rowcount)
        db.session.commit()
        return granted
