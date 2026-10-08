"""What the API sends, field by field. Nothing is passed through from the logic
modules' dicts wholesale: those carry Profile objects and datetimes, and spelling
the fields out is how the privacy rules hold. Another person's lifts and cardio
never include notes, and a body weight is only ever in the owner's own payload."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import url_for

from .. import session_meta, sessions


def timestamp(value: datetime | None) -> str | None:
    """A naive-UTC datetime as '2026-10-06T18:04:05Z'."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc, microsecond=0).isoformat().replace("+00:00", "Z")


def person(profile) -> dict | None:
    """A profile as anyone may see it. Never the email address."""
    if profile is None:
        return None
    return {
        "handle": profile.handle,
        "name": profile.display_name,
        "avatar_url": profile.avatar_url or None,
        "bio": profile.bio or "",
    }


def own_profile(profile) -> dict | None:
    """Your own profile, with the invite link only you may hand out."""
    if profile is None:
        return None
    return {
        **person(profile),
        "invite_url": url_for("social.invite", code=profile.invite_code, _external=True),
    }


def _tags(value: str | None) -> list[str]:
    return [t.strip() for t in (value or "").split(";") if t.strip()]


def lift(row: dict, mine: bool) -> dict:
    out = {
        "id": row["id"],
        "exercise": row["exercise"],
        "weight": row["weight"],
        "sets": row["sets"],
        "reps": row["reps"],
        "sets_reps": row.get("sets_reps", ""),
        "tags": _tags(row.get("tags")),
        "pr": bool(row.get("pr")),
    }
    if mine:
        out["notes"] = row.get("notes", "")
    return out


def cardio(row: dict, mine: bool) -> dict:
    out = {
        "id": row["id"],
        "activity": row["activity"],
        "distance": row["distance"],
        "duration": row["duration"],
    }
    if mine:
        out["notes"] = row.get("notes", "")
    return out


def lines(rows: list[dict]) -> list[dict]:
    """One line per exercise, the same ones the session cards show."""
    return [
        {"exercise": ln["exercise"], "detail": ln["detail"], "parts": ln["parts"], "pr": ln["pr"]}
        for ln in sessions.exercise_lines(rows)
    ]


def comment(c: dict) -> dict:
    return {
        "id": c["id"],
        "body": c["body"],
        "at": timestamp(c["at"]),
        "author": person(c["author"]),
        "can_delete": bool(c["can_delete"]),
    }


def reactions(card: dict | None) -> dict | None:
    """High fives and comments, for a card social.attach_social() has been over."""
    if not card or "kudos" not in card:
        return None
    return {
        "kudos": card["kudos"],
        "kudoed": bool(card["kudoed"]),
        "comments": [comment(c) for c in card["comments"]],
    }


def stats(summary: dict) -> dict:
    return {
        "exercises": summary["exercises"],
        "entries": summary["entries"],
        "sets": summary["sets"],
        "reps": summary["reps"],
        "volume": summary["volume"],
        "cardio_distance": summary["cardio"]["distance_text"],
        "cardio_minutes": summary["cardio"]["minutes_text"],
    }


def my_card(card: dict | None) -> dict | None:
    """One of your own workouts, as routes._my_day_card() builds it."""
    if card is None:
        return None
    return {
        "date": card["date"],
        "session": card["session"],
        "title": card["title"],
        "icon_hint": card["share"]["hint"],
        "stat_line": card["share"]["stat_line"],
        "lifts": [lift(r, mine=True) for r in card["rows"]],
        "cardio": [cardio(c, mine=True) for c in card["cardio"]],
        "lines": lines(card["rows"]),
        "bodyweight": card["weight"]["weight"] if card["weight"] else None,
        "reactions": reactions(card),
    }


def friend_card(card: dict) -> dict:
    """Someone else's workout, as social.session_cards() builds it from
    visible_data(). No notes and no body weight, whatever the card holds."""
    return {
        "owner": person(card["owner"]),
        "date": card["date"],
        "session": card["session"],
        "title": card["title"],
        "icon_hint": session_meta.icon_hint(card["rows"], card["cardio"]),
        "lifts": [lift(r, mine=False) for r in card["rows"]],
        "cardio": [cardio(c, mine=False) for c in card["cardio"]],
        "lines": lines(card["rows"]),
        "prs": card.get("prs", 0),
        "reactions": reactions(card),
    }


def week_day(d: dict) -> dict:
    keys = ("date", "letter", "day", "logged", "rest", "today", "future", "exercises", "sets")
    return {**{k: d[k] for k in keys}, "cardio": d["cardio_text"], "bodyweight": d["weight"]}


def recent(s: dict) -> dict:
    return {
        "date": s["date"],
        "session": s["session"],
        "title": s["title"],
        "summary": s["summary"],
    }


def parsed_entry(e: dict) -> dict:
    return {k: e[k] for k in ("exercise", "weight", "sets", "reps", "notes")}


def parsed_cardio(c: dict) -> dict:
    return {k: c[k] for k in ("activity", "distance", "duration", "notes")}


def day(parts: dict) -> dict:
    """Your own day, as routes.day_parts() builds it."""
    return {
        "date": parts["when"],
        "session": parts["n"],
        "title": parts["title"],
        "icon_hint": parts["share"]["hint"],
        "stat_line": parts["share"]["stat_line"],
        "sessions": [{"session": s["n"], "title": s["title"]} for s in parts["switcher"]],
        "lifts": [lift(r, mine=True) for r in parts["rows"]],
        "cardio": [cardio(c, mine=True) for c in parts["cardio"]],
        "lines": lines(parts["rows"]),
        "bodyweight": parts["weight"]["weight"] if parts["weight"] else None,
        "stats": stats(parts["summary"]),
        "reactions": reactions(parts["thread"]),
        "previous": parts["prev"],
        "next": parts["nxt"],
    }


# --- Progress -------------------------------------------------------------------


def rest_rule(rule: dict) -> dict:
    return {k: rule[k] for k in ("id", "kind", "weekdays", "interval_days", "anchor_date")}


def _lift_progress(item: dict) -> dict:
    keys = ("exercise", "first", "latest", "change", "pct", "unit")
    return {**{k: item[k] for k in keys}, "series": [dict(p) for p in item["series"]]}


def _bodyweight(bw: dict | None) -> dict | None:
    """Your own weigh-ins over the range. Only ever in the owner's payload."""
    if bw is None:
        return None
    keys = ("latest", "latest_date", "change", "unit", "since", "chart_unit", "charted")
    return {**{k: bw[k] for k in keys}, "periods": [dict(p) for p in bw["periods"]]}


def progress(parts: dict) -> dict:
    """Your Progress overview, as routes.progress_parts() builds it."""
    data = parts["data"]
    totals, activity = data["totals"], data["cardio"]
    return {
        "range": data["range"],
        "by": data["by"],
        "start": data["start"].isoformat() if data["start"] else None,
        "total": parts["total"],
        "totals": {
            "sessions": totals["sessions"],
            "entries": totals["entries"],
            "exercises": totals["exercises"],
            "volume": totals["volume"],
            "cardio": totals["cardio"],
            "cardio_distance": activity["distance_text"],
            "cardio_minutes": activity["minutes_text"],
        },
        "streak": data["streak"],
        "per_period": [dict(p) for p in data["per_period"]],
        "week": {
            "start": parts["week_param"],
            "end": parts["week_end"].isoformat(),
            "previous": parts["prev_week"],
            "next": parts["next_week"],
            "is_this_week": parts["is_this_week"],
            "days": [week_day(d) for d in data["week"]],
        },
        "rest_rules": [rest_rule(r) for r in parts["rest_rules"]],
        "bodyweight": _bodyweight(data["bodyweight"]),
        "lifts": [_lift_progress(x) for x in data["lifts"]],
        "tags": [dict(t) for t in data["tags"]],
        "top_exercises": [dict(e) for e in data["top_exercises"]],
        "prs": [
            {
                "exercise": r["exercise"],
                "date": r["date"],
                "session": r.get("session", 0),
                "weight": r["weight"],
                "value": r["value"],
                "previous": r["previous"],
            }
            for r in data["prs"]
        ],
    }


def session_tile(d: dict) -> dict:
    """One of your workouts on the Sessions list, as routes.sessions_parts() builds it."""
    return {
        "date": d["date"],
        "session": d["session"],
        "title": d["title"],
        "icon_hint": session_meta.icon_hint(d["rows"], d["cardio"]),
        "lines": [
            {"name": ln["name"], "detail": ln["detail"], "parts": ln["parts"], "pr": ln["pr"]}
            for ln in d["lines"]
        ],
        "bodyweight": d["weight"]["weight"] if d["weight"] else None,
    }


def exercise_row(e: dict) -> dict:
    return {k: e[k] for k in ("exercise", "entries", "sessions", "first", "last", "best", "spark")}


def cardio_row(c: dict) -> dict:
    return {
        "activity": c["activity"],
        "count": c["count"],
        "distance": c["distance_text"],
        "minutes": c["minutes_text"],
        "last": c["last"],
    }


def exercise(parts: dict) -> dict:
    """One of your exercises over time, as routes.exercise_parts() builds it."""
    lift_progress = parts["lift"]
    return {
        "name": parts["name"],
        "tags": _tags(parts["tags"]),
        "total": parts["total"],
        "sessions": parts["sessions"],
        "best": dict(parts["best"]) if parts["best"] else None,
        "volume": parts["volume"],
        "last_date": parts["last_date"],
        "series": [dict(p) for p in parts["series"]],
        "progress": _lift_progress(lift_progress) if lift_progress else None,
        "entries": [
            {
                **lift(dict(r, sets_reps=sessions.sets_summary(r["sets"], r["reps"])), mine=True),
                "date": r["date"],
                "session": r.get("session", 0),
            }
            for r in parts["rows"]
        ],
    }
