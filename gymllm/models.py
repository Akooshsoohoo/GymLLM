"""Database models. The schema intentionally matches the pre-existing
production table so deployed data keeps working without a migration."""

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
