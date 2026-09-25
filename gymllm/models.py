"""Database models. The Workout schema intentionally matches the pre-existing
production table so deployed data keeps working without a migration; the newer
tables are created by db.create_all() on first start."""

from __future__ import annotations

from datetime import datetime, timezone

from .extensions import db

FIELDS = ("date", "exercise", "weight", "sets", "reps", "notes", "tags")


class Workout(db.Model):
    __tablename__ = "workout"

    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    exercise = db.Column(db.String, nullable=False)
    weight = db.Column(db.String, nullable=True)
    sets = db.Column(db.String, nullable=True)
    reps = db.Column(db.String, nullable=True)
    notes = db.Column(db.String, nullable=True)
    tags = db.Column(db.String, nullable=True)

    def as_dict(self) -> dict:
        return {"id": self.id, **{f: getattr(self, f) or "" for f in FIELDS}}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Workout {self.id} {self.date} {self.exercise}>"


CARDIO_FIELDS = ("date", "activity", "distance", "duration", "notes")
BODYWEIGHT_FIELDS = ("date", "weight", "notes")


class Cardio(db.Model):
    """A distance- or time-based activity: a walk, run, swim, ride, hike..."""

    __tablename__ = "cardio"

    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False, index=True)
    date = db.Column(db.String, nullable=False)
    activity = db.Column(db.String, nullable=False)
    distance = db.Column(db.String, nullable=True)  # as written: "3 miles", "5 km"
    duration = db.Column(db.String, nullable=True)  # as written: "45 min", "1 h 10 min"
    notes = db.Column(db.String, nullable=True)

    def as_dict(self) -> dict:
        return {"id": self.id, **{f: getattr(self, f) or "" for f in CARDIO_FIELDS}}


class BodyWeight(db.Model):
    """One body-weight reading per user per day."""

    __tablename__ = "body_weight"
    __table_args__ = (db.UniqueConstraint("user_email", "date", name="uq_body_weight_user_day"),)

    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False, index=True)
    date = db.Column(db.String, nullable=False)
    weight = db.Column(db.String, nullable=False)  # as written: "130 lbs", "82 kg"
    notes = db.Column(db.String, nullable=True)

    def as_dict(self) -> dict:
        return {"id": self.id, **{f: getattr(self, f) or "" for f in BODYWEIGHT_FIELDS}}


class LLMUsage(db.Model):
    """How many parses a user has made with the site's shared model on a given day."""

    __tablename__ = "llm_usage"
    __table_args__ = (db.UniqueConstraint("user_email", "day", name="uq_llm_usage_user_day"),)

    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False, index=True)
    day = db.Column(db.String, nullable=False)  # YYYY-MM-DD, UTC
    count = db.Column(db.Integer, nullable=False, default=0)


class UserPreference(db.Model):
    """Small per-account settings that aren't the LLM provider config (that one
    lives in a session cookie, see LLMConfig)."""

    __tablename__ = "user_preference"

    user_email = db.Column(db.String, primary_key=True)
    weight_unit = db.Column(db.String, nullable=False, default="lbs")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Social ---------------------------------------------------------------------
# A "session" is one user's day: kudos and comments point at (owner_email, date).


class Profile(db.Model):
    """The public face of an account: a unique handle, a name and what friends see."""

    __tablename__ = "profile"

    user_email = db.Column(db.String, primary_key=True)
    handle = db.Column(db.String(20), nullable=False, unique=True)  # lowercase
    display_name = db.Column(db.String(60), nullable=False)
    avatar_url = db.Column(db.String, nullable=True)
    bio = db.Column(db.String(160), nullable=True)
    share_bodyweight = db.Column(db.Boolean, nullable=False, default=False)
    invite_code = db.Column(db.String(24), nullable=False, unique=True)
    activity_seen_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class Friendship(db.Model):
    """A friend request (pending) or a friendship (accepted). One row per pair."""

    __tablename__ = "friendship"
    __table_args__ = (
        db.UniqueConstraint("requester_email", "addressee_email", name="uq_friendship_pair"),
    )

    id = db.Column(db.Integer, primary_key=True)
    requester_email = db.Column(db.String, nullable=False, index=True)
    addressee_email = db.Column(db.String, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="pending")  # pending | accepted
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)


class Kudos(db.Model):
    __tablename__ = "kudos"
    __table_args__ = (
        db.UniqueConstraint("owner_email", "date", "giver_email", name="uq_kudos_once"),
        db.Index("ix_kudos_session", "owner_email", "date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    owner_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    giver_email = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class Comment(db.Model):
    __tablename__ = "comment"
    __table_args__ = (db.Index("ix_comment_session", "owner_email", "date"),)

    id = db.Column(db.Integer, primary_key=True)
    owner_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    author_email = db.Column(db.String, nullable=False)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
