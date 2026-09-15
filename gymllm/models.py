"""Database models. The Workout schema intentionally matches the pre-existing
production table so deployed data keeps working without a migration; the newer
tables are created by db.create_all() on first start."""

from __future__ import annotations

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
