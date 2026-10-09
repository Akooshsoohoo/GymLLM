"""Deleting an account: every row that names the email, in every table, and a cutoff
that makes the sign-ins issued before it stop working.

The app's bearer tokens and the site's cookie session are both signed and stateless,
so neither can be taken back one at a time. Instead a deleted account leaves an
AccountCutoff row: a keyed hash of the email and the moment of deletion. A token or a
cookie issued at or before that moment is refused; signing in again afterwards starts
a new, empty account."""

from __future__ import annotations

import hashlib
import hmac
import time

from flask import current_app
from sqlalchemy import inspect, or_, text

from .extensions import db
from .models import (
    AccountCutoff,
    BodyWeight,
    Cardio,
    Comment,
    Friendship,
    Kudos,
    LLMUsage,
    ParseLog,
    Profile,
    RestOverride,
    RestRule,
    Routine,
    RoutineBlock,
    SessionInfo,
    SessionMeta,
    SessionVisibility,
    UserActivity,
    UserPreference,
    Workout,
)

# A cutoff outlives the longest sign-in: auth.API_TOKEN_MAX_AGE, which is also
# PERMANENT_SESSION_LIFETIME. After that nothing it could refuse is still valid.
CUTOFF_KEPT = 30 * 24 * 60 * 60  # seconds

# Rows that are the account's own, by the column holding its email.
_OWN = (
    (Workout, "user_email"),
    (Cardio, "user_email"),
    (BodyWeight, "user_email"),
    (LLMUsage, "user_email"),
    (UserActivity, "user_email"),
    (ParseLog, "user_email"),
    (UserPreference, "user_email"),
    (Profile, "user_email"),
    (SessionVisibility, "owner_email"),
    (SessionMeta, "owner_email"),
    (SessionInfo, "owner_email"),
    (RestRule, "owner_email"),
    (RestOverride, "owner_email"),
)


def _email_hash(email: str) -> str:
    key = str(current_app.config["SECRET_KEY"]).encode()
    return hmac.new(key, b"account-cutoff:" + email.encode(), hashlib.sha256).hexdigest()


def revoked(email: str, issued_at: int | float | None) -> bool:
    """Whether a sign-in for `email` issued at `issued_at` (seconds since the epoch)
    was cut off by the account being deleted. One with no time on it predates the
    cutoffs and counts as issued before any of them."""
    row = db.session.get(AccountCutoff, _email_hash(email))
    return row is not None and (issued_at or 0) <= row.not_before


def delete(email: str) -> None:
    """Remove everything stored for `email` and cut off its outstanding sign-ins.
    Includes what it left on other people's workouts (high fives, comments) and what
    they left on its own, and both sides of every friendship and request."""
    for model, column in _OWN:
        model.query.filter(getattr(model, column) == email).delete(synchronize_session=False)
    Kudos.query.filter(or_(Kudos.owner_email == email, Kudos.giver_email == email)).delete(
        synchronize_session=False
    )
    Comment.query.filter(or_(Comment.owner_email == email, Comment.author_email == email)).delete(
        synchronize_session=False
    )
    Friendship.query.filter(
        or_(Friendship.requester_email == email, Friendship.addressee_email == email)
    ).delete(synchronize_session=False)
    # By hand rather than by the foreign key's cascade, which SQLite only honours
    # when asked to.
    routine_ids = [r.id for r in Routine.query.filter_by(user_email=email)]
    if routine_ids:
        RoutineBlock.query.filter(RoutineBlock.routine_id.in_(routine_ids)).delete(
            synchronize_session=False
        )
        Routine.query.filter(Routine.id.in_(routine_ids)).delete(synchronize_session=False)
    # The table session_kudos replaced. migrate.py copies its rows over at every
    # start, so high fives left there would come back.
    # Looked up on the session's own connection: on the in-memory database of the
    # tests a second one is the same one, and handing it back undoes the deletes above.
    if "kudos" in inspect(db.session.connection()).get_table_names():
        db.session.execute(
            text("DELETE FROM kudos WHERE owner_email = :email OR giver_email = :email"),
            {"email": email},
        )

    now = int(time.time())
    AccountCutoff.query.filter(AccountCutoff.not_before < now - CUTOFF_KEPT).delete(
        synchronize_session=False
    )
    cutoff = db.session.get(AccountCutoff, _email_hash(email))
    if cutoff is None:
        db.session.add(AccountCutoff(email_hash=_email_hash(email), not_before=now))
    else:
        cutoff.not_before = now
    db.session.commit()
    db.session.expire_all()
