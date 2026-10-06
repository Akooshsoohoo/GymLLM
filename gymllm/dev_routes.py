"""Local-only routes for browsing the app without Google OAuth: a handful of
seeded fake accounts, already friends with each other, so every page --
including friends/feed/compare -- has real-looking data. Never registered in
production; see the IS_PRODUCTION check in gymllm/__init__.py."""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, redirect, render_template, session, url_for

from . import social
from .extensions import db
from .models import BodyWeight, Cardio, Workout

bp = Blueprint("dev", __name__, url_prefix="/dev")

DEV_USERS = [
    {"slug": "alex", "email": "dev-alex@example.test", "handle": "alex", "display_name": "Alex Dev"},
    {"slug": "sam", "email": "dev-sam@example.test", "handle": "sam", "display_name": "Sam Dev"},
    {"slug": "jordan", "email": "dev-jordan@example.test", "handle": "jordan", "display_name": "Jordan Dev"},
]  # fmt: skip

_EXERCISES = [
    ("barbell bench press", "chest;push", 135),
    ("back squat", "legs;push", 185),
    ("deadlift", "back;pull", 225),
    ("overhead press", "shoulders;push", 95),
    ("barbell row", "back;pull", 135),
]
_VISIBILITIES = (social.PRIVATE, social.FRIENDS_ONLY, social.FRIENDS_ONLY)
_WEEKS = 8


def _seed_user(email: str) -> None:
    today = date.today()
    for week in range(_WEEKS):
        for day_offset in (0, 2, 4):
            when = (today - timedelta(days=week * 7 + day_offset)).isoformat()
            exercise, tags, base_weight = _EXERCISES[(week + day_offset) % len(_EXERCISES)]
            db.session.add(
                Workout(
                    user_email=email,
                    date=when,
                    exercise=exercise,
                    weight=f"{base_weight + week * 5} lbs",
                    sets="3",
                    reps="8, 8, 8",
                    notes="",
                    tags=tags,
                )
            )
            social.set_visibility(email, when, _VISIBILITIES[(week + day_offset) % 3])
        cardio_day = (today - timedelta(days=week * 7 + 1)).isoformat()
        db.session.add(
            Cardio(
                user_email=email,
                date=cardio_day,
                activity="run",
                distance="3 miles",
                duration="28 min",
            )
        )
        weigh_in_day = (today - timedelta(days=week * 7)).isoformat()
        db.session.add(BodyWeight(user_email=email, date=weigh_in_day, weight="180 lbs"))
    db.session.commit()


def _ensure_seeded() -> None:
    """Idempotent: skips entirely once the first dev user already has a profile."""
    if social.get_profile(DEV_USERS[0]["email"]) is not None:
        return
    for u in DEV_USERS:
        social.save_profile(u["email"], u["handle"], u["display_name"])
        _seed_user(u["email"])
    for a in DEV_USERS:
        for b in DEV_USERS:
            if a["email"] != b["email"]:
                social.befriend(a["email"], b["email"])

    alex, sam, jordan = (u["email"] for u in DEV_USERS)
    today = date.today().isoformat()
    social.set_visibility(
        alex, today, social.FRIENDS_ONLY
    )  # so the seeded activity below is visible
    db.session.commit()
    social.toggle_kudos(sam, alex, today)
    social.add_comment(jordan, alex, today, "Nice work!")


@bp.route("/")
def index():
    return render_template("dev/index.html", dev_users=DEV_USERS)


@bp.route("/login/<slug>")
def login(slug: str):
    user = next((u for u in DEV_USERS if u["slug"] == slug), None)
    if user is None:
        return redirect(url_for("dev.index"))
    _ensure_seeded()
    session["user_email"] = user["email"]
    session.permanent = True
    return redirect(url_for("main.home"))
