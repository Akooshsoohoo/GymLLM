"""Friends: your profile, other people's, friendships, invites, the feed, high
fives, comments and Compare. Each endpoint mirrors one handler in social_routes.py,
and anything about another person comes through social.visible_data(), can_view()
or has_session(), never from their rows directly."""

from __future__ import annotations

from datetime import timedelta

from flask import jsonify, request, url_for

from .. import auth, preferences, social, stats
from .. import compare as compare_mod
from ..auth import current_user_email
from ..parsing import is_iso_date
from ..routes import _client_today
from ..social_routes import PROFILE_RECENT
from . import bp, schema
from .errors import ApiError, json_body, not_found, profile_required, token_required


def _claim(key: str) -> str:
    claims, _ = auth.api_token_claims()
    return (claims or {}).get(key) or ""


def _other(handle: str):
    """The profile behind `handle` or 404."""
    profile = social.profile_by_handle(handle)
    if profile is None:
        raise not_found("Nobody has that handle.")
    return profile


def _invite_url(profile) -> str:
    return url_for("social.invite", code=profile.invite_code, _external=True)


# --- Your profile -----------------------------------------------------------------


@bp.route("/profile")
@token_required
def profile_get():
    """Mirrors the GET of social_routes.profile_edit: your profile, or what the setup
    form starts from. ?invite= keeps whoever invited you in view."""
    email = current_user_email()
    profile = social.get_profile(email)
    name = _claim("name")
    inviter = social.profile_by_invite(request.args.get("invite", "")) if not profile else None
    return jsonify(
        profile=schema.own_profile(profile),
        suggested={
            "handle": profile.handle if profile else social.suggest_handle(email, name),
            "name": profile.display_name if profile else (name or email.split("@")[0]),
            "bio": (profile.bio or "") if profile else "",
        },
        inviter=schema.person(inviter),
    )


def _field(data: dict, key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{key} must be text.")
    return value


@bp.route("/profile", methods=["PUT"])
@token_required
def profile_put():
    """Mirrors the POST of social_routes.profile_edit: create or change your profile."""
    data = json_body()
    email = current_user_email()
    handle = social.clean_handle(_field(data, "handle"))
    error = social.handle_error(handle, email)
    if error is not None:
        raise ApiError(422, "bad_handle", error)
    created = social.get_profile(email) is None
    profile = social.save_profile(
        email,
        handle,
        _field(data, "name"),
        _field(data, "bio"),
        avatar_url=_claim("picture") or None,
    )
    return jsonify(profile=schema.own_profile(profile), created=created), (201 if created else 200)


@bp.route("/profile/invite-reset", methods=["POST"])
@profile_required
def invite_reset():
    profile = social.get_profile(current_user_email())
    social.reset_invite(profile)
    return jsonify(
        invite_url=_invite_url(profile),
        message="New invite link made. The old one no longer works.",
    )


# --- Other people -----------------------------------------------------------------


@bp.route("/u/<handle>")
@profile_required
def profile(handle: str):
    """Mirrors social_routes.profile. A stranger gets who it is and nothing else."""
    viewer = current_user_email()
    other = _other(handle)
    rel = social.relationship(viewer, other.user_email)
    out = {
        "person": schema.person(other),
        "relationship": rel,
        "friend_count": len(social.friend_emails(other.user_email)),
        "visible": False,
    }
    data = social.visible_data(viewer, other.user_email)
    if data is None:
        return jsonify(out)
    rows, cardio, _ = data
    today = _client_today()
    last_30 = stats.filter_range(rows, today, "30d"), stats.filter_range(cardio, today, "30d")
    favourites = stats.top_exercises(
        stats.filter_range(rows, today, "90d"), 5
    ) or stats.top_exercises(rows, 5)
    cards = social.attach_social(social.session_cards(viewer, other, limit=PROFILE_RECENT), viewer)
    totals = stats.totals(*last_30)
    return jsonify(
        **{**out, "visible": True},
        # No weigh-ins go in, your own included: a profile is what friends see.
        week=[schema.profile_week_day(d) for d in stats.week_strip(today, rows, cardio)],
        streak=stats.week_streak({x["date"] for x in rows + cardio}, today),
        last_30={
            "sessions": totals["sessions"],
            "sets": sum(stats.set_count(r.get("sets"), r.get("reps")) for r in last_30[0]),
            "cardio_minutes": round(totals["minutes"]),
        },
        favourites=[schema.favourite(f) for f in favourites],
        prs=[schema.pr(r) for r in stats.personal_records(rows, today - timedelta(days=90))[:5]],
        cards=[schema.friend_card(c) for c in cards],
        total=len(rows) + len(cardio),
    )


@bp.route("/u/<handle>/compare")
@profile_required
def compare(handle: str):
    """Mirrors social_routes.compare: you beside a friend."""
    viewer = current_user_email()
    other = _other(handle)
    if other.user_email == viewer or not social.can_view(viewer, other.user_email):
        raise not_found()
    mine = social.visible_data(viewer, viewer)
    theirs = social.visible_data(viewer, other.user_email)
    range_key = stats.clean_range(request.args.get("range"), default="30d")
    data = compare_mod.compare(
        mine[:2],
        theirs[:2],
        _client_today(),
        range_key,
        preferences.get_weight_unit(viewer),
        preferences.get_weight_unit(other.user_email),
    )
    return jsonify(
        me=schema.person(social.get_profile(viewer)),
        other=schema.person(other),
        range=range_key,
        **schema.compare(data),
    )


# --- Friends ----------------------------------------------------------------------


@bp.route("/friends")
@profile_required
def friends():
    """Mirrors social_routes.friends, and like it marks the activity as seen."""
    email = current_user_email()
    me_profile = social.get_profile(email)
    q = request.args.get("q", "").strip()
    results = [
        {**schema.person(p), "relationship": social.relationship(email, p.user_email)}
        for p in (social.search(q, email) if q else [])
    ]
    incoming, outgoing = social.pending(email)
    seen_at = me_profile.activity_seen_at
    activity = social.activity_on_mine(email)
    social.mark_seen(me_profile)
    return jsonify(
        q=q,
        results=results,
        incoming=[schema.person(p) for p in incoming],
        outgoing=[schema.person(p) for p in outgoing],
        friends=[
            schema.person(p)
            for p in sorted(
                social.profiles_for(social.friend_emails(email)).values(),
                key=lambda p: p.display_name.lower(),
            )
        ],
        activity=[schema.activity(e, seen_at) for e in activity],
        invite_url=_invite_url(me_profile),
    )


@bp.route("/friends/<action>/<handle>", methods=["POST"])
@profile_required
def friend_action(action: str, handle: str):
    """Mirrors social_routes.friend_action: request, accept, decline, cancel, remove."""
    email = current_user_email()
    other = _other(handle)
    name = other.display_name
    message = ""
    if action == "request":
        rel = social.request_friend(email, other.user_email)
        message = (
            f"You and {name} are now friends."
            if rel == social.FRIENDS
            else f"Friend request sent to {name}."
        )
    elif action == "accept":
        if social.accept(email, other.user_email):
            message = f"You and {name} are now friends."
    elif action in ("decline", "cancel", "remove"):
        social.unlink(email, other.user_email)
    else:
        raise not_found()
    return jsonify(
        person=schema.person(other),
        relationship=social.relationship(email, other.user_email),
        message=message,
    )


@bp.route("/invite/<code>", methods=["GET", "POST"])
@profile_required
def invite(code: str):
    """Mirrors social_routes.invite: GET says whose link it is, POST makes you
    friends at once (they handed the link out)."""
    owner = social.profile_by_invite(code)
    if owner is None:
        raise not_found("That invite link doesn't work any more. Ask for a new one.")
    email = current_user_email()
    rel = social.relationship(email, owner.user_email)
    message = ""
    if request.method == "POST" and rel not in (social.SELF, social.FRIENDS):
        social.befriend(email, owner.user_email)
        rel = social.FRIENDS
        message = f"You and {owner.display_name} are now friends."
    return jsonify(person=schema.person(owner), relationship=rel, message=message)


# --- Feed, high fives and comments ------------------------------------------------


@bp.route("/feed")
@profile_required
def feed():
    """Mirrors social_routes.feed. ?before= is the last page's `next_before`."""
    email = current_user_email()
    before = request.args.get("before")
    before = before if before and is_iso_date(before) else None
    cards, next_before = social.feed(email, before=before)
    return jsonify(
        cards=[schema.friend_card(c) for c in cards],
        next_before=next_before,
        has_friends=bool(social.friend_emails(email)),
    )


def _session_owner(handle: str, when: str, n: int):
    """The owner of a workout the viewer may react to, or 404."""
    owner = _other(handle)
    if not is_iso_date(when) or not social.has_session(
        current_user_email(), owner.user_email, when, n
    ):
        raise not_found("No such workout.")
    return owner


def _reactions(owner, when: str, n: int) -> dict:
    """The high fives and comments now on one workout, as the viewer sees them."""
    card = {"owner": owner, "date": when, "session": n}
    return schema.reactions(social.attach_social([card], current_user_email())[0])


@bp.route("/kudos/<handle>/<when>", methods=["POST"])
@bp.route("/kudos/<handle>/<when>/<int:n>", methods=["POST"])
@profile_required
def kudos(handle: str, when: str, n: int = 0):
    """Mirrors social_routes.kudos: give a high five, or take it back."""
    owner = _session_owner(handle, when, n)
    if owner.user_email == current_user_email():
        raise not_found()  # high fives are for friends' workouts
    count, mine = social.toggle_kudos(current_user_email(), owner.user_email, when, n)
    return jsonify(count=count, mine=mine)


@bp.route("/comments/<handle>/<when>", methods=["POST"])
@bp.route("/comments/<handle>/<when>/<int:n>", methods=["POST"])
@profile_required
def comment(handle: str, when: str, n: int = 0):
    """Mirrors social_routes.comment. Answers with the workout's reactions as they
    now stand."""
    owner = _session_owner(handle, when, n)
    body = _field(json_body(), "body")
    if social.add_comment(current_user_email(), owner.user_email, when, body, n) is None:
        raise ApiError(422, "empty_comment", "Write something first.")
    return jsonify(_reactions(owner, when, n)), 201


@bp.route("/comments/<int:comment_id>", methods=["DELETE"])
@profile_required
def comment_delete(comment_id: int):
    """Mirrors social_routes.comment_delete: yours, or one on your own workout."""
    c = social.delete_comment(current_user_email(), comment_id)
    if c is None:
        raise not_found("No such comment.")
    owner = social.get_profile(c.owner_email)
    # Someone who is no longer a friend may still take their own comment back, but
    # gets none of the others in return.
    if owner is None or not social.has_session(
        current_user_email(), c.owner_email, c.date, c.session
    ):
        return jsonify(kudos=0, kudoed=False, comments=[])
    return jsonify(_reactions(owner, c.date, c.session))
