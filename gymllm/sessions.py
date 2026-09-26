"""Loading a user's log and grouping it into sessions (one session = one day with
anything logged). Shared by the Log page, the day page and the social views."""

from __future__ import annotations

from . import stats
from .models import BodyWeight, Cardio, Workout

RECENT_SESSIONS = 5


def all_of(model, user_email: str) -> list[dict]:
    """Every row of `model` for the user as dicts, newest first."""
    rows = (
        model.query.filter_by(user_email=user_email)
        .order_by(model.date.desc(), model.id.desc())
        .all()
    )
    return [r.as_dict() for r in rows]


def all_rows(user_email: str) -> list[dict]:
    return all_of(Workout, user_email)


def all_cardio(user_email: str) -> list[dict]:
    return all_of(Cardio, user_email)


def all_weights(user_email: str) -> list[dict]:
    return all_of(BodyWeight, user_email)


def sets_summary(sets: str, reps: str) -> str:
    """Reps per set, comma-separated: sets='3', reps='10, 8, 6' -> '10, 8, 6'. A
    single reps number is repeated across the set count: sets='5', reps='12' ->
    '12, 12, 12, 12, 12'."""
    parts = stats.reps_list(reps)
    if len(parts) == 1 and (sets or "").strip().isdigit() and int(sets) > 1:
        parts = parts * int(sets)
    if parts:
        return ", ".join(str(p) for p in parts)
    return sets or reps


def group_sessions(
    rows: list[dict],
    cardio: list[dict],
    weights: list[dict],
    limit: int | None = None,
    before: str | None = None,
) -> list[dict]:
    """The days with anything logged (strictly before `before`, if given), newest
    first, each with its strength entries, cardio, and weigh-in. Rows are expected
    newest first, as all_of() returns them."""
    dates = {r["date"] for r in rows} | {c["date"] for c in cardio} | {w["date"] for w in weights}
    if before:
        dates = {d for d in dates if d < before}
    sessions = []
    for day in sorted(dates, reverse=True)[:limit]:
        strength = [
            dict(r, sets_reps=sets_summary(r["sets"], r["reps"])) for r in rows if r["date"] == day
        ]
        sessions.append(
            {
                "date": day,
                "rows": strength,
                "cardio": [c for c in cardio if c["date"] == day],
                "weight": next((w for w in weights if w["date"] == day), None),
            }
        )
    return sessions


def compact_sets(sets_reps: str) -> str:
    """'5, 5, 5, 5, 5' -> '5×5'; anything uneven or single is left as is."""
    parts = [p.strip() for p in (sets_reps or "").split(",")]
    if len(parts) > 1 and len(set(parts)) == 1 and parts[0].isdigit():
        return f"{len(parts)}×{parts[0]}"
    return sets_reps or ""


def activity_count(session: dict) -> str:
    """'3 exercises' when there are lifts (cardio counts too), else '2 activities'."""
    n = len({r["exercise"] for r in session.get("rows", [])}) + len(session.get("cardio", []))
    if session.get("rows"):
        return f"{n} exercise{'' if n == 1 else 's'}"
    return f"{n} activit{'y' if n == 1 else 'ies'}"


def session_summary(session: dict) -> str:
    """A one-line label for a day: 'Chest · 4 exercises', 'Walking · 3 miles'."""
    rows, cardio = session.get("rows", []), session.get("cardio", [])
    if rows:
        tags = [t["tag"] for t in stats.tag_counts(rows) if t["tag"] != "other"]
        lead = tags[0] if tags else rows[-1]["exercise"]
        return f"{lead[:1].upper()}{lead[1:]} · {activity_count(session)}"
    if cardio:
        c = cardio[-1]
        detail = c.get("distance") or c.get("duration") or ""
        name = c["activity"][:1].upper() + c["activity"][1:]
        return f"{name} · {detail}" if detail else name
    if session.get("weight"):
        return f"Weighed in · {session['weight']['weight']}"
    return ""


def recent_sessions(user_email: str, limit: int = RECENT_SESSIONS) -> list[dict]:
    """The user's most recent days with anything logged, newest first."""
    return group_sessions(
        all_rows(user_email), all_cardio(user_email), all_weights(user_email), limit
    )
