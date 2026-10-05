"""A session's own details on top of its lifts and cardio: a title and, later, a photo.

Templates never choose between the photo and the icon themselves; they render
whatever visual() returns. Photos plug in by storing a key in SessionInfo.photo_key
and teaching photo_url() to turn it into a URL."""

from __future__ import annotations

from datetime import date

from .extensions import db
from .models import Comment, Kudos, SessionInfo, SessionVisibility
from .stats import MOVEMENT_TAGS

TITLE_MAX = 80


def default_title(when: str, n: int = 0) -> str:
    """'2026-09-22' -> 'Tuesday workout'; a day's later sessions count on: 'Tuesday
    workout 2'."""
    name = f"{date.fromisoformat(when):%A} workout"
    return name if n == 0 else f"{name} {n + 1}"


def get(owner: str, when: str, n: int = 0) -> SessionInfo | None:
    return db.session.get(SessionInfo, (owner, when, n))


def for_days(owner: str, dates) -> dict[tuple[str, int], SessionInfo]:
    """{(date, session): SessionInfo} for the given days' sessions that have one, in a
    single query."""
    dates = list(dates)
    if not dates:
        return {}
    rows = SessionInfo.query.filter(
        SessionInfo.owner_email == owner, SessionInfo.date.in_(dates)
    ).all()
    return {(m.date, m.session): m for m in rows}


def title_for(when: str, meta: SessionInfo | None, n: int = 0) -> str:
    return (meta.title if meta and meta.title else "") or default_title(when, n)


def _drop_if_empty(meta: SessionInfo) -> None:
    if not meta.title and not meta.photo_key:
        db.session.delete(meta)


def set_title(owner: str, when: str, n: int, title: str | None) -> None:
    """Rename a session. Blank, or the default itself, goes back to the default. The
    caller commits."""
    title = " ".join((title or "").split())[:TITLE_MAX]
    if title == default_title(when, n):
        title = ""
    meta = get(owner, when, n)
    if meta is None:
        if title:
            db.session.add(SessionInfo(owner_email=owner, date=when, session=n, title=title))
        return
    meta.title = title or None
    _drop_if_empty(meta)


def move_session(owner: str, old: str, old_n: int, new: str, new_n: int) -> None:
    """Carry a session's title and photo to its new date and number. The caller
    commits."""
    row = get(owner, old, old_n)
    if row is None:
        return
    db.session.add(SessionInfo(**{**_columns(row), "date": new, "session": new_n}))
    db.session.delete(row)
    db.session.flush()  # so later lookups by (owner, new, new_n) see the moved row


def move_reactions(owner: str, old: str, old_n: int, new: str, new_n: int) -> None:
    """Carry a session's kudos and comments along with it. The caller commits."""
    for model in (Kudos, Comment):
        for row in model.query.filter_by(owner_email=owner, date=old, session=old_n):
            row.date, row.session = new, new_n


def clear_session(owner: str, when: str, n: int) -> None:
    """Forget a session's title, photo, kudos and comments once nothing is logged in
    it. The caller commits."""
    row = get(owner, when, n)
    if row is not None:
        db.session.delete(row)
    for model in (Kudos, Comment):
        model.query.filter_by(owner_email=owner, date=when, session=n).delete()


def clear_day_visibility(owner: str, when: str) -> None:
    """Forget who may see a day once nothing is logged on it."""
    row = db.session.get(SessionVisibility, (owner, when))
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


def visual(session: dict, meta: SessionInfo | None) -> dict:
    """{"kind": "photo", "url"} when the session has a photo, else {"kind": "icon", "hint"}."""
    url = photo_url(meta.photo_key) if meta and meta.photo_key else None
    if url:
        return {"kind": "photo", "url": url}
    return {
        "kind": "icon",
        "hint": icon_hint(session.get("rows", []), session.get("cardio", [])),
    }
