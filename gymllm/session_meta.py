"""A day's own details on top of its lifts and cardio: a title and, later, a photo.

Templates never choose between the photo and the icon themselves; they render
whatever visual() returns. Photos plug in by storing a key in SessionMeta.photo_key
and teaching photo_url() to turn it into a URL."""

from __future__ import annotations

from datetime import date

from .extensions import db
from .models import SessionMeta, SessionVisibility
from .stats import MOVEMENT_TAGS

TITLE_MAX = 80


def default_title(when: str) -> str:
    """'2026-09-22' -> 'Tuesday workout'."""
    return f"{date.fromisoformat(when):%A} workout"


def get(owner: str, when: str) -> SessionMeta | None:
    return db.session.get(SessionMeta, (owner, when))


def for_days(owner: str, dates) -> dict[str, SessionMeta]:
    """{date: SessionMeta} for the given days that have one, in a single query."""
    dates = list(dates)
    if not dates:
        return {}
    rows = SessionMeta.query.filter(
        SessionMeta.owner_email == owner, SessionMeta.date.in_(dates)
    ).all()
    return {m.date: m for m in rows}


def title_for(when: str, meta: SessionMeta | None) -> str:
    return (meta.title if meta and meta.title else "") or default_title(when)


def _drop_if_empty(meta: SessionMeta) -> None:
    if not meta.title and not meta.photo_key:
        db.session.delete(meta)


def set_title(owner: str, when: str, title: str | None) -> None:
    """Rename a day. Blank, or the default itself, goes back to the default. The
    caller commits."""
    title = " ".join((title or "").split())[:TITLE_MAX]
    if title == default_title(when):
        title = ""
    meta = get(owner, when)
    if meta is None:
        if title:
            db.session.add(SessionMeta(owner_email=owner, date=when, title=title))
        return
    meta.title = title or None
    _drop_if_empty(meta)


def move_day(owner: str, old: str, new: str) -> None:
    """Carry a day's title, photo and visibility to another date. When the new date
    already has its own, those win. The caller commits."""
    for model in (SessionMeta, SessionVisibility):
        row = db.session.get(model, (owner, old))
        if row is None:
            continue
        if db.session.get(model, (owner, new)) is None:
            db.session.add(model(**{**_columns(row), "date": new}))
        db.session.delete(row)
    db.session.flush()  # so later lookups by (owner, new) see the moved rows


def clear_day(owner: str, when: str) -> None:
    """Forget a day's title, photo and visibility once nothing is logged on it."""
    for model in (SessionMeta, SessionVisibility):
        row = db.session.get(model, (owner, when))
        if row is not None:
            db.session.delete(row)


def _columns(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def photo_url(key: str | None) -> str | None:
    """The URL of a stored photo. Photos aren't built yet, so there is never one."""
    return None


def icon_hint(rows: list[dict], cardio: list[dict]) -> str:
    """What the browser's MuscleIcons.forTags() picks the day's icon from: the muscle
    tags of its lifts (the name when a lift has none) and its cardio activities."""
    words: list[str] = []
    for r in rows:
        tags = [t.strip() for t in (r.get("tags") or "").split(";")]
        tags = [t for t in tags if t and t not in MOVEMENT_TAGS]
        words.extend(tags or [r["exercise"]])
    words.extend(c["activity"] for c in cardio)
    seen: list[str] = []
    for w in words:
        w = w.lower()
        if w not in seen:
            seen.append(w)
    return ", ".join(seen)


def visual(session: dict, meta: SessionMeta | None) -> dict:
    """{"kind": "photo", "url"} when the day has a photo, else {"kind": "icon", "hint"}."""
    url = photo_url(meta.photo_key) if meta and meta.photo_key else None
    if url:
        return {"kind": "photo", "url": url}
    return {
        "kind": "icon",
        "hint": icon_hint(session.get("rows", []), session.get("cardio", [])),
    }
