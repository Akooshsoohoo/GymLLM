"""A stats dashboard restricted to ADMIN_EMAILS. Reads only tables that already
exist -- there's no request/traffic logging in the app, so this reports usage
counts (users, workouts, friendships...), not visit counts."""

from __future__ import annotations

from flask import Blueprint, render_template
from sqlalchemy import func

from . import activity
from .auth import admin_required
from .extensions import db
from .models import BodyWeight, Cardio, Friendship, Profile, UserActivity, UserPreference, Workout

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _known_emails() -> list[str]:
    """Everyone who has ever signed in, logged a workout, saved a preference,
    or made a profile -- the closest proxy to "every account" since there's
    no User table."""
    rows = (
        db.session.query(UserActivity.user_email)
        .union(db.session.query(Workout.user_email))
        .union(db.session.query(UserPreference.user_email))
        .union(db.session.query(Profile.user_email))
        .all()
    )
    return sorted({r[0] for r in rows})


@bp.route("/")
@admin_required
def index():
    emails = _known_emails()
    workout_counts = dict(
        db.session.query(Workout.user_email, func.count(Workout.id))
        .group_by(Workout.user_email)
        .all()
    )
    last_workout = dict(
        db.session.query(Workout.user_email, func.max(Workout.date))
        .group_by(Workout.user_email)
        .all()
    )
    handles = {p.user_email: p.handle for p in Profile.query.all()}
    last_seen = {a.user_email: a.last_active_date for a in UserActivity.query.all()}

    users = sorted(
        (
            {
                "email": e,
                "handle": handles.get(e),
                "workouts": workout_counts.get(e, 0),
                "last_workout": last_workout.get(e),
                "last_seen": last_seen.get(e),
            }
            for e in emails
        ),
        key=lambda u: u["workouts"],
        reverse=True,
    )
    active = activity.active_counts()
    stats = {
        "total_users": len(emails),
        "active_today": active["today"],
        "active_this_week": active["this_week"],
        "parses_today": activity.parses_today(),
        "total_workouts": Workout.query.count(),
        "total_cardio": Cardio.query.count(),
        "total_bodyweight": BodyWeight.query.count(),
        "total_profiles": Profile.query.count(),
        "total_friendships": Friendship.query.filter_by(status="accepted").count(),
    }
    return render_template("admin/index.html", stats=stats, users=users)
