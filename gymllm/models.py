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
    # Which of the day's logged workouts this belongs to (0 = the first). Added after
    # launch: db.create_all() can't add it to an existing table, see migrate.py.
    session = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            **{f: getattr(self, f) or "" for f in FIELDS},
            "session": self.session or 0,
        }

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
    session = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            **{f: getattr(self, f) or "" for f in CARDIO_FIELDS},
            "session": self.session or 0,
        }


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


class UserActivity(db.Model):
    """Cheap 'who's around' signal for the admin dashboard: the last UTC day
    each known user was seen. Updated at most once per day, not per request."""

    __tablename__ = "user_activity"

    user_email = db.Column(db.String, primary_key=True)
    last_active_date = db.Column(db.String, nullable=False)  # YYYY-MM-DD, UTC


class ParseLog(db.Model):
    """How many workouts a user parsed on a given day, with any provider --
    unlike LLMUsage, which only caps the shared site model."""

    __tablename__ = "parse_log"
    __table_args__ = (db.UniqueConstraint("user_email", "day", name="uq_parse_log_user_day"),)

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
# A "session" is one logged workout: a user's day can hold several, and kudos and
# comments point at (owner_email, date, session).


class Profile(db.Model):
    """The public face of an account: a unique handle, a name and what friends see."""

    __tablename__ = "profile"

    user_email = db.Column(db.String, primary_key=True)
    handle = db.Column(db.String(20), nullable=False, unique=True)  # lowercase
    display_name = db.Column(db.String(60), nullable=False)
    avatar_url = db.Column(db.String, nullable=True)
    bio = db.Column(db.String(160), nullable=True)
    # No longer read: body weight is never shown to anyone else. Kept so inserts
    # still fill the existing NOT NULL column.
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


class SessionVisibility(db.Model):
    """Who may see one day's lifts and cardio. A day with no row is friends-only."""

    __tablename__ = "session_visibility"

    owner_email = db.Column(db.String, primary_key=True)
    date = db.Column(db.String, primary_key=True)
    visibility = db.Column(db.String(10), nullable=False)  # private | friends | public


class SessionMeta(db.Model):
    """Legacy: one title per day. Superseded by SessionInfo, which migrate.py copies it
    into; nothing reads or writes this table any more."""

    __tablename__ = "session_meta"

    owner_email = db.Column(db.String, primary_key=True)
    date = db.Column(db.String, primary_key=True)
    title = db.Column(db.String(80), nullable=True)
    photo_key = db.Column(db.String, nullable=True)


class SessionInfo(db.Model):
    """One logged workout's own details: the title you gave it and, later, its photo.
    A session with no row uses the default title and its muscle icon."""

    __tablename__ = "session_info"

    owner_email = db.Column(db.String, primary_key=True)
    date = db.Column(db.String, primary_key=True)
    session = db.Column(db.Integer, primary_key=True, default=0)
    title = db.Column(db.String(80), nullable=True)
    # Where the photo is stored; nothing writes it yet (see session_meta.photo_url).
    photo_key = db.Column(db.String, nullable=True)


class RestRule(db.Model):
    """A recurring rest schedule: fixed weekdays, or every N days from an anchor."""

    __tablename__ = "rest_rule"

    id = db.Column(db.Integer, primary_key=True)
    owner_email = db.Column(db.String, nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # weekdays | interval
    weekdays = db.Column(db.String(20), nullable=True)  # "0,6" (Mon=0), weekdays rules
    interval_days = db.Column(db.Integer, nullable=True)  # interval rules
    anchor_date = db.Column(db.String, nullable=True)  # interval rules: a rest day

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "weekdays": [int(x) for x in (self.weekdays or "").split(",") if x],
            "interval_days": self.interval_days,
            "anchor_date": self.anchor_date,
        }


class RestOverride(db.Model):
    """One day's rest, set by hand: True forces rest, False cancels a scheduled one."""

    __tablename__ = "rest_override"

    owner_email = db.Column(db.String, primary_key=True)
    date = db.Column(db.String, primary_key=True)
    is_rest = db.Column(db.Boolean, nullable=False)


class Kudos(db.Model):
    # Was "kudos", unique per (owner, date, giver); a new table so the uniqueness can
    # include the session. migrate.py copies the old rows over.
    __tablename__ = "session_kudos"
    __table_args__ = (
        db.UniqueConstraint(
            "owner_email", "date", "session", "giver_email", name="uq_session_kudos_once"
        ),
        db.Index("ix_session_kudos_session", "owner_email", "date", "session"),
    )

    id = db.Column(db.Integer, primary_key=True)
    owner_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    session = db.Column(db.Integer, nullable=False, default=0)
    giver_email = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class Comment(db.Model):
    __tablename__ = "comment"
    __table_args__ = (db.Index("ix_comment_session", "owner_email", "date"),)

    id = db.Column(db.Integer, primary_key=True)
    owner_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    session = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    author_email = db.Column(db.String, nullable=False)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


# --- Routines -------------------------------------------------------------------
# A named template of named blocks that pre-fills the recorder. The body stays free
# text on purpose: it is exactly what the parser reads once the workout is done.


class Routine(db.Model):
    __tablename__ = "routine"

    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class RoutineBlock(db.Model):
    __tablename__ = "routine_block"

    id = db.Column(db.Integer, primary_key=True)
    routine_id = db.Column(
        db.Integer, db.ForeignKey("routine.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(40), nullable=True)
    body = db.Column(db.Text, nullable=False, default="")
