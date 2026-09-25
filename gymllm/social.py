"""Profiles, friendships, kudos and comments, and what one user may see of another.

Every social view reads another user's log through visible_data(), which is the
only place the privacy rules live: friends (and yourself) only, notes stripped,
body weight only when its owner shares it."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import and_, or_

from . import sessions, stats
from .extensions import db
from .models import Comment, Friendship, Kudos, Profile

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,20}$")
RESERVED_HANDLES = {
    "admin", "api", "edit", "feed", "friends", "gymllm", "help", "invite", "login",
    "logout", "me", "new", "profile", "root", "settings", "setup", "support", "system",
}  # fmt: skip
NAME_MAX = 60
BIO_MAX = 160
COMMENT_MAX = 500
FEED_PAGE = 20
SEARCH_LIMIT = 10

SELF, FRIENDS, OUTGOING, INCOMING, NONE = "self", "friends", "outgoing", "incoming", "none"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Profiles -------------------------------------------------------------------


def get_profile(email: str | None) -> Profile | None:
    return db.session.get(Profile, email) if email else None


def profile_by_handle(handle: str) -> Profile | None:
    return Profile.query.filter_by(handle=clean_handle(handle)).first()


def profile_by_invite(code: str) -> Profile | None:
    return Profile.query.filter_by(invite_code=code).first() if code else None


def profiles_for(emails) -> dict[str, Profile]:
    emails = set(emails)
    if not emails:
        return {}
    return {p.user_email: p for p in Profile.query.filter(Profile.user_email.in_(emails))}


def clean_handle(raw: str | None) -> str:
    return (raw or "").strip().lstrip("@").lower()


def handle_error(handle: str, email: str) -> str | None:
    """Why `handle` can't be used by `email`, or None if it can."""
    if not HANDLE_RE.match(handle):
        return "Handles are 3 to 20 characters: lowercase letters, numbers and underscores."
    if handle in RESERVED_HANDLES:
        return "That handle is reserved. Try another."
    taken = Profile.query.filter_by(handle=handle).first()
    if taken and taken.user_email != email:
        return "That handle is taken."
    return None


def suggest_handle(email: str, name: str | None = None) -> str:
    """A free handle based on the name or the email's local part."""
    base = re.sub(r"[^a-z0-9_]", "", (name or email.split("@")[0]).lower().replace(" ", "_"))
    base = (base or "lifter")[:16].ljust(3, "0")
    candidate, n = base, 1
    while handle_error(candidate, email):
        n += 1
        candidate = f"{base[:16]}{n}"
    return candidate


def new_invite_code() -> str:
    return secrets.token_urlsafe(9)


def save_profile(
    email: str,
    handle: str,
    display_name: str,
    bio: str = "",
    share_bodyweight: bool = False,
    avatar_url: str | None = None,
) -> Profile:
    """Create or update the profile. The caller validates the handle first."""
    profile = get_profile(email)
    if profile is None:
        profile = Profile(user_email=email, invite_code=new_invite_code(), activity_seen_at=_now())
        db.session.add(profile)
    profile.handle = handle
    profile.display_name = display_name.strip()[:NAME_MAX] or handle
    profile.bio = bio.strip()[:BIO_MAX] or None
    profile.share_bodyweight = share_bodyweight
    if avatar_url:
        profile.avatar_url = avatar_url
    db.session.commit()
    return profile


def reset_invite(profile: Profile) -> str:
    profile.invite_code = new_invite_code()
    db.session.commit()
    return profile.invite_code


def search(q: str, viewer: str, limit: int = SEARCH_LIMIT) -> list[Profile]:
    """Profiles whose handle starts with `q` (exact match first), yourself excluded."""
    q = clean_handle(q)
    if not q or not re.fullmatch(r"[a-z0-9_]+", q):
        return []
    found = (
        Profile.query.filter(Profile.handle.startswith(q), Profile.user_email != viewer)
        .order_by(Profile.handle)
        .limit(limit)
        .all()
    )
    return sorted(found, key=lambda p: p.handle != q)


# --- Friendships ----------------------------------------------------------------


def _pair(a: str, b: str) -> Friendship | None:
    return Friendship.query.filter(
        or_(
            and_(Friendship.requester_email == a, Friendship.addressee_email == b),
            and_(Friendship.requester_email == b, Friendship.addressee_email == a),
        )
    ).first()


def relationship(viewer: str, other: str) -> str:
    if viewer == other:
        return SELF
    f = _pair(viewer, other)
    if f is None:
        return NONE
    if f.status == "accepted":
        return FRIENDS
    return OUTGOING if f.requester_email == viewer else INCOMING


def friend_emails(email: str) -> set[str]:
    rows = Friendship.query.filter(
        Friendship.status == "accepted",
        or_(Friendship.requester_email == email, Friendship.addressee_email == email),
    )
    return {f.addressee_email if f.requester_email == email else f.requester_email for f in rows}


def pending(email: str) -> tuple[list[Profile], list[Profile]]:
    """(incoming, outgoing) friend requests as profiles, newest first."""
    rows = (
        Friendship.query.filter(
            Friendship.status == "pending",
            or_(Friendship.requester_email == email, Friendship.addressee_email == email),
        )
        .order_by(Friendship.created_at.desc())
        .all()
    )
    profiles = profiles_for(
        f.requester_email if f.addressee_email == email else f.addressee_email for f in rows
    )
    incoming = [profiles[f.requester_email] for f in rows if f.addressee_email == email]
    outgoing = [profiles[f.addressee_email] for f in rows if f.requester_email == email]
    return [p for p in incoming if p], [p for p in outgoing if p]


def request_friend(viewer: str, other: str) -> str:
    """Send a request; if `other` already asked `viewer`, this accepts it instead."""
    if viewer == other:
        return SELF
    f = _pair(viewer, other)
    if f is None:
        db.session.add(Friendship(requester_email=viewer, addressee_email=other))
    elif f.status == "pending" and f.addressee_email == viewer:
        f.status, f.accepted_at = "accepted", _now()
    db.session.commit()
    return relationship(viewer, other)


def accept(viewer: str, other: str) -> bool:
    f = _pair(viewer, other)
    if f is None or f.status != "pending" or f.addressee_email != viewer:
        return False
    f.status, f.accepted_at = "accepted", _now()
    db.session.commit()
    return True


def unlink(viewer: str, other: str) -> bool:
    """Decline or cancel a request, or unfriend: the pair is forgotten either way."""
    f = _pair(viewer, other)
    if f is None:
        return False
    db.session.delete(f)
    db.session.commit()
    return True


def befriend(viewer: str, other: str) -> None:
    """Make the two friends at once (the invite-link path: the owner shared it)."""
    if viewer == other:
        return
    f = _pair(viewer, other)
    if f is None:
        f = Friendship(requester_email=other, addressee_email=viewer)
        db.session.add(f)
    if f.status != "accepted":
        f.status, f.accepted_at = "accepted", _now()
    db.session.commit()


# --- What a viewer may see ------------------------------------------------------


def can_view(viewer: str, owner: str) -> bool:
    return relationship(viewer, owner) in (SELF, FRIENDS)


def visible_data(viewer: str, owner: str) -> tuple[list[dict], list[dict], list[dict]] | None:
    """(rows, cardio, weights) of `owner` as `viewer` may see them, or None if
    they may not see any of it. Newest first, like sessions.all_of()."""
    if not can_view(viewer, owner):
        return None
    rows, cardio, weights = (
        sessions.all_rows(owner),
        sessions.all_cardio(owner),
        sessions.all_weights(owner),
    )
    if viewer == owner:
        return rows, cardio, weights
    profile = get_profile(owner)
    rows = [dict(r, notes="") for r in rows]
    cardio = [dict(c, notes="") for c in cardio]
    weights = weights if profile and profile.share_bodyweight else []
    return rows, cardio, weights


def has_session(viewer: str, owner: str, when: str) -> bool:
    """Whether `owner` logged lifts or cardio on `when` and `viewer` may see it."""
    data = visible_data(viewer, owner)
    return bool(data) and any(x["date"] == when for x in data[0] + data[1])


def mark_prs(session: dict, all_rows: list[dict]) -> dict:
    """Flag the session's rows that set a new best weight for their exercise."""
    prs = {r["id"] for r in stats.personal_records(all_rows, None) if r["date"] == session["date"]}
    session["rows"] = [dict(r, pr=r["id"] in prs) for r in session["rows"]]
    session["prs"] = sum(1 for r in session["rows"] if r["pr"])
    return session


# --- Kudos and comments ---------------------------------------------------------


def toggle_kudos(giver: str, owner: str, when: str) -> tuple[int, bool]:
    k = Kudos.query.filter_by(owner_email=owner, date=when, giver_email=giver).first()
    if k:
        db.session.delete(k)
    else:
        db.session.add(Kudos(owner_email=owner, date=when, giver_email=giver))
    db.session.commit()
    return Kudos.query.filter_by(owner_email=owner, date=when).count(), k is None


def add_comment(author: str, owner: str, when: str, body: str) -> Comment | None:
    body = (body or "").strip()
    if not body:
        return None
    c = Comment(owner_email=owner, date=when, author_email=author, body=body[:COMMENT_MAX])
    db.session.add(c)
    db.session.commit()
    return c


def delete_comment(viewer: str, comment_id: int) -> Comment | None:
    """Delete a comment its author or the session's owner asked to remove."""
    c = db.session.get(Comment, comment_id)
    if c is None or viewer not in (c.author_email, c.owner_email):
        return None
    db.session.delete(c)
    db.session.commit()
    return c


def attach_social(cards: list[dict], viewer: str) -> list[dict]:
    """Add kudos (count, whether the viewer gave one) and comments to session
    cards, which carry "owner" (a Profile) and "date"."""
    if not cards:
        return cards
    owners = {c["owner"].user_email for c in cards}
    dates = {c["date"] for c in cards}
    kudos = Kudos.query.filter(Kudos.owner_email.in_(owners), Kudos.date.in_(dates)).all()
    comments = (
        Comment.query.filter(Comment.owner_email.in_(owners), Comment.date.in_(dates))
        .order_by(Comment.created_at, Comment.id)
        .all()
    )
    authors = profiles_for(c.author_email for c in comments)
    for card in cards:
        key = (card["owner"].user_email, card["date"])
        givers = [k.giver_email for k in kudos if (k.owner_email, k.date) == key]
        card["kudos"] = len(givers)
        card["kudoed"] = viewer in givers
        card["comments"] = [
            {"id": c.id, "body": c.body, "at": c.created_at, "author": authors.get(c.author_email),
             "can_delete": viewer in (c.author_email, c.owner_email)}
            for c in comments
            if (c.owner_email, c.date) == key
        ]  # fmt: skip
    return cards


def session_cards(
    viewer: str, owner: Profile, limit: int | None = None, before: str | None = None
) -> list[dict]:
    """One owner's sessions as cards, with PR flags. Weigh-in-only days are left
    out: the feed is for workouts."""
    data = visible_data(viewer, owner.user_email)
    if not data:
        return []
    rows, cardio, weights = data
    days = [
        s
        for s in sessions.group_sessions(rows, cardio, weights, before=before)
        if s["rows"] or s["cardio"]
    ][:limit]
    return [dict(mark_prs(s, rows), owner=owner) for s in days]


def feed(
    viewer: str, before: str | None = None, limit: int = FEED_PAGE
) -> tuple[list[dict], str | None]:
    """Friends' sessions newest first, and the `before` value for the next page
    (None on the last page). A page never splits a date across two pages."""
    owners = profiles_for(friend_emails(viewer)).values()
    cards = [c for p in owners for c in session_cards(viewer, p, limit=limit + 1, before=before)]
    cards.sort(key=lambda c: (c["date"], c["owner"].display_name.lower()), reverse=True)
    if len(cards) <= limit:
        return attach_social(cards, viewer), None
    cut = cards[limit - 1]["date"]
    page = [c for c in cards if c["date"] >= cut]
    return attach_social(page, viewer), cut


# --- Activity on your own sessions ----------------------------------------------


def activity_on_mine(email: str, limit: int = 20) -> list[dict]:
    """Recent kudos and comments others left on `email`'s sessions, newest first."""
    kudos = (
        Kudos.query.filter(Kudos.owner_email == email, Kudos.giver_email != email)
        .order_by(Kudos.created_at.desc())
        .limit(limit)
        .all()
    )
    comments = (
        Comment.query.filter(Comment.owner_email == email, Comment.author_email != email)
        .order_by(Comment.created_at.desc())
        .limit(limit)
        .all()
    )
    who = profiles_for([k.giver_email for k in kudos] + [c.author_email for c in comments])
    events = [
        {
            "kind": "kudos",
            "who": who.get(k.giver_email),
            "date": k.date,
            "at": k.created_at,
            "body": "",
        }
        for k in kudos
    ]
    events += [{"kind": "comment", "who": who.get(c.author_email), "date": c.date, "at": c.created_at, "body": c.body} for c in comments]  # fmt: skip
    events = [e for e in events if e["who"]]
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


def unseen_count(email: str) -> int:
    """Incoming friend requests plus others' kudos and comments on your sessions
    since you last opened the Friends page."""
    profile = get_profile(email)
    if profile is None:
        return 0
    n = Friendship.query.filter_by(addressee_email=email, status="pending").count()
    since = profile.activity_seen_at or profile.created_at
    n += Kudos.query.filter(
        Kudos.owner_email == email, Kudos.giver_email != email, Kudos.created_at > since
    ).count()
    n += Comment.query.filter(
        Comment.owner_email == email, Comment.author_email != email, Comment.created_at > since
    ).count()
    return n


def mark_seen(profile: Profile) -> None:
    profile.activity_seen_at = _now()
    db.session.commit()
