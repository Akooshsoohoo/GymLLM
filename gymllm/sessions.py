"""Loading a user's log and grouping it into sessions (one session = one workout you
logged; a day can hold several, numbered 0, 1, 2... in the order they were saved).
Shared by the Log page, the day page and the social views."""

from __future__ import annotations

from . import stats
from .extensions import db
from .models import BodyWeight, Cardio, RestOverride, RestRule, Workout

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


def rest_rules(user_email: str) -> list[dict]:
    rules = RestRule.query.filter_by(owner_email=user_email).order_by(RestRule.id).all()
    return [r.as_dict() for r in rules]


def rest_overrides(user_email: str) -> dict[str, bool]:
    return {o.date: o.is_rest for o in RestOverride.query.filter_by(owner_email=user_email).all()}


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


def session_numbers(rows: list[dict], cardio: list[dict]) -> dict[str, list[int]]:
    """{date: [session numbers, ascending]} for every day with lifts or cardio."""
    found: dict[str, set[int]] = {}
    for x in rows + cardio:
        found.setdefault(x["date"], set()).add(x.get("session", 0))
    return {d: sorted(n) for d, n in found.items()}


def next_session(user_email: str, when: str) -> int:
    """The number a workout saved on `when` now gets: one past the day's last."""
    best = -1
    for model in (Workout, Cardio):
        top = (
            db.session.query(db.func.max(model.session))
            .filter(model.user_email == user_email, model.date == when)
            .scalar()
        )
        if top is not None:
            best = max(best, top)
    return best + 1


def group_sessions(
    rows: list[dict],
    cardio: list[dict],
    weights: list[dict],
    limit: int | None = None,
    before: str | None = None,
) -> list[dict]:
    """The logged workouts (on days strictly before `before`, if given), newest day
    first and, within a day, the last saved first. Each has its strength entries and
    cardio; the day's weigh-in rides on the day's first session (or stands alone on
    a day with nothing else). Rows are expected newest first, as all_of() returns them."""
    numbers = session_numbers(rows, cardio)
    for w in weights:
        numbers.setdefault(w["date"], [0])
    if before:
        numbers = {d: n for d, n in numbers.items() if d < before}
    keys = [(d, n) for d in sorted(numbers, reverse=True) for n in reversed(numbers[d])]
    sessions = []
    for day, n in keys[:limit]:
        strength = [
            dict(r, sets_reps=sets_summary(r["sets"], r["reps"]))
            for r in rows
            if r["date"] == day and r.get("session", 0) == n
        ]
        sessions.append(
            {
                "date": day,
                "session": n,
                "rows": strength,
                "cardio": [c for c in cardio if c["date"] == day and c.get("session", 0) == n],
                "weight": (
                    next((w for w in weights if w["date"] == day), None)
                    if n == numbers[day][0]
                    else None
                ),
            }
        )
    return sessions


def compact_sets(sets_reps: str) -> str:
    """'5, 5, 5, 5, 5' -> '5×5'; anything uneven or single is left as is."""
    parts = [p.strip() for p in (sets_reps or "").split(",")]
    if len(parts) > 1 and len(set(parts)) == 1 and parts[0].isdigit():
        return f"{len(parts)}×{parts[0]}"
    return sets_reps or ""


def _weight_parts(entries: list[dict]) -> list[str]:
    """An exercise logged at several weights, one clause per weight in the order first
    logged: ['30 lbs · 8, 8, 5', '40 lbs · 3×8']. Entries at the same weight are merged
    ('30' and '30 lbs' are the same weight) and their reps run together. A weight with
    no number ('bodyweight') is its own clause, keyed by its text."""
    unit = next(
        (q[1] for q in map(stats.quantity, (e["weight"] for e in entries)) if q and q[1]), ""
    )
    clauses: dict[object, list] = {}  # weight key -> [label, [reps...]]
    for e in entries:
        amount = stats.quantity(e["weight"])
        if amount:
            number, own_unit = amount
            key = number
            label = f"{stats.format_number(number)} {own_unit or unit}".strip()
        else:
            key = (e["weight"] or "").strip().lower()
            label = (e["weight"] or "").strip()
        clause = clauses.setdefault(key, [label, []])
        clause[1] += stats.reps_list(e.get("sets_reps", ""))
    parts = []
    for label, reps in clauses.values():
        reps_text = compact_sets(", ".join(str(n) for n in reps))
        parts.append(" · ".join(p for p in (label, reps_text) if p))
    return [p for p in parts if p]


def exercise_lines(rows: list[dict]) -> list[dict]:
    """A day's lifts (in log order) as one entry per exercise, in first-appearance
    order: [{"exercise", "detail", "parts", "sub", "pr"}]. An exercise logged once keeps
    its own one-liner in `detail` ('185 lbs · 5×5'). One logged at several weights has
    no `detail`; its weights go on a second line: `parts` (one clause per weight) and
    `sub` (the clauses joined: '30 lbs · 8, 8, 5, 40 lbs · 3×8'). `pr` is set when any
    of its entries is a new best."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["exercise"].strip().lower(), []).append(r)
    lines = []
    for entries in groups.values():
        first = entries[0]
        if len(entries) == 1:
            detail = " · ".join(
                p for p in (first["weight"], compact_sets(first.get("sets_reps", ""))) if p
            )
            parts = []
        else:
            detail, parts = "", _weight_parts(entries)
        lines.append(
            {
                "exercise": first["exercise"],
                "detail": detail,
                "parts": parts,
                "sub": ", ".join(parts),
                "pr": any(e.get("pr") for e in entries),
            }
        )
    return lines


def activity_count(session: dict) -> str:
    """Lifts and cardio counted apart: '3 exercises', '3 exercises · 1 cardio',
    '2 cardio'. An exercise logged at several weights counts once."""
    lifts = len({r["exercise"] for r in session.get("rows", [])})
    cardio = len(session.get("cardio", []))
    parts = []
    if lifts:
        parts.append(f"{lifts} exercise{'' if lifts == 1 else 's'}")
    if cardio:
        parts.append(f"{cardio} cardio")
    return " · ".join(parts)


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
