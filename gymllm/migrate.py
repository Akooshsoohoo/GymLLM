"""Schema changes db.create_all() can't make on a table that already exists. Run once
at startup, after create_all(); every step checks first, so re-running is harmless.

Several workouts a day (see sessions.py): workout, cardio and comment gain a `session`
column (existing rows are session 0), and the per-day tables session_meta and kudos
are copied into session_info and session_kudos, which key on the session too.

Onboarding: user_preference gains `onboarding_dismissed`."""

from __future__ import annotations

from sqlalchemy import inspect, text

from .extensions import db

_ADD_SESSION = ("workout", "cardio", "comment")


def run() -> None:
    insp = inspect(db.engine)
    with db.engine.begin() as conn:
        for table in _ADD_SESSION:
            if table in insp.get_table_names() and "session" not in {
                c["name"] for c in insp.get_columns(table)
            }:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN session INTEGER NOT NULL DEFAULT 0")
                )
        names = insp.get_table_names()
        if "user_preference" in names and "onboarding_dismissed" not in {
            c["name"] for c in insp.get_columns("user_preference")
        }:
            conn.execute(
                text(
                    "ALTER TABLE user_preference ADD COLUMN onboarding_dismissed "
                    "BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
        if "session_meta" in names:
            conn.execute(
                text(
                    "INSERT INTO session_info (owner_email, date, session, title, photo_key) "
                    "SELECT m.owner_email, m.date, 0, m.title, m.photo_key FROM session_meta m "
                    "WHERE NOT EXISTS (SELECT 1 FROM session_info i WHERE "
                    "i.owner_email = m.owner_email AND i.date = m.date AND i.session = 0)"
                )
            )
        if "kudos" in names:
            conn.execute(
                text(
                    "INSERT INTO session_kudos (owner_email, date, session, giver_email, created_at) "
                    "SELECT k.owner_email, k.date, 0, k.giver_email, k.created_at FROM kudos k "
                    "WHERE NOT EXISTS (SELECT 1 FROM session_kudos n WHERE "
                    "n.owner_email = k.owner_email AND n.date = k.date AND n.session = 0 "
                    "AND n.giver_email = k.giver_email)"
                )
            )
