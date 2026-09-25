"""Profiles, friends, the activity feed, kudos, comments and Compare."""

from __future__ import annotations

from datetime import timedelta
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import compare as compare_mod
from . import preferences, social, stats
from .auth import (
    AFTER_LOGIN,
    SESSION_GOOGLE_NAME,
    SESSION_GOOGLE_PICTURE,
    current_user_email,
    login_required,
    safe_next,
)
from .parsing import is_iso_date
from .routes import _client_today

bp = Blueprint("social", __name__)

PROFILE_RECENT = 3


def profile_required(view):
    """Signed in and with a profile; otherwise off to set one up, then back here."""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if social.get_profile(current_user_email()) is None:
            return redirect(url_for("social.profile_edit", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def _back(default: str, anchor: str = "") -> str:
    """Where a form post returns to: its `next` field when safe, else `default`."""
    return (safe_next(request.form.get("next")) or default) + anchor


def _other(handle: str):
    """The profile behind `handle` or 404."""
    profile = social.profile_by_handle(handle)
    if profile is None:
        abort(404)
    return profile


def _wants_json() -> bool:
    return request.accept_mimetypes.best == "application/json"


# --- Profile setup ----------------------------------------------------------------


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def profile_edit():
    email = current_user_email()
    profile = social.get_profile(email)
    next_url = safe_next(request.values.get("next"))
    error = None
    if request.method == "POST":
        handle = social.clean_handle(request.form.get("handle"))
        error = social.handle_error(handle, email)
        if error is None:
            first_time = profile is None
            profile = social.save_profile(
                email,
                handle,
                request.form.get("display_name", ""),
                request.form.get("bio", ""),
                request.form.get("share_bodyweight") == "on",
                avatar_url=session.get(SESSION_GOOGLE_PICTURE) or None,
            )
            flash("Profile created. Find friends below." if first_time else "Profile saved.", "ok")
            if next_url:
                return redirect(next_url)
            return redirect(
                url_for("social.friends" if first_time else "social.profile", handle=profile.handle)
            )
        form = request.form
    else:
        name = session.get(SESSION_GOOGLE_NAME) or ""
        form = {
            "handle": profile.handle if profile else social.suggest_handle(email, name),
            "display_name": profile.display_name if profile else (name or email.split("@")[0]),
            "bio": (profile.bio or "") if profile else "",
            "share_bodyweight": "on" if profile and profile.share_bodyweight else "",
        }
    return render_template(
        "profile_edit.html", profile=profile, form=form, error=error, next_url=next_url
    ), (400 if error else 200)


@bp.route("/profile/invite-reset", methods=["POST"])
@profile_required
def invite_reset():
    social.reset_invite(social.get_profile(current_user_email()))
    flash("New invite link made. The old one no longer works.", "ok")
    return redirect(url_for("social.friends"))


@bp.route("/me")
@profile_required
def me():
    return redirect(
        url_for("social.profile", handle=social.get_profile(current_user_email()).handle)
    )


# --- Profile page -----------------------------------------------------------------


@bp.route("/u/<handle>")
@profile_required
def profile(handle: str):
    viewer = current_user_email()
    other = _other(handle)
    rel = social.relationship(viewer, other.user_email)
    ctx = {"other": other, "rel": rel, "friend_count": len(social.friend_emails(other.user_email))}
    data = social.visible_data(viewer, other.user_email)
    if data is None:
        return render_template("profile.html", **ctx)
    rows, cardio, weights = data
    today = _client_today()
    last_30 = stats.filter_range(rows, today, "30d"), stats.filter_range(cardio, today, "30d")
    favourites = stats.top_exercises(
        stats.filter_range(rows, today, "90d"), 5
    ) or stats.top_exercises(rows, 5)
    cards = social.attach_social(social.session_cards(viewer, other, limit=PROFILE_RECENT), viewer)
    return render_template(
        "profile.html",
        **ctx,
        week=stats.week_strip(today, rows, cardio, weights),
        streak=stats.week_streak({x["date"] for x in rows + cardio}, today),
        totals=stats.totals(*last_30),
        sets=sum(stats.set_count(r.get("sets"), r.get("reps")) for r in last_30[0]),
        favourites=favourites,
        prs=stats.personal_records(rows, today - timedelta(days=90))[:5],
        cards=cards,
        total=len(rows) + len(cardio),
    )


@bp.route("/u/<handle>/compare")
@profile_required
def compare(handle: str):
    viewer = current_user_email()
    other = _other(handle)
    if other.user_email == viewer or not social.can_view(viewer, other.user_email):
        abort(404)
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
    return render_template(
        "compare.html",
        me=social.get_profile(viewer),
        other=other,
        data=data,
        range_key=range_key,
    )


# --- Friends ----------------------------------------------------------------------


@bp.route("/friends")
@profile_required
def friends():
    email = current_user_email()
    me_profile = social.get_profile(email)
    q = request.args.get("q", "").strip()
    results = (
        [(p, social.relationship(email, p.user_email)) for p in social.search(q, email)]
        if q
        else []
    )
    incoming, outgoing = social.pending(email)
    seen_at = me_profile.activity_seen_at
    activity = social.activity_on_mine(email)
    social.mark_seen(me_profile)
    return render_template(
        "friends.html",
        me=me_profile,
        q=q,
        results=results,
        incoming=incoming,
        outgoing=outgoing,
        friends=sorted(
            social.profiles_for(social.friend_emails(email)).values(),
            key=lambda p: p.display_name.lower(),
        ),
        activity=activity,
        seen_at=seen_at,
        invite_url=url_for("social.invite", code=me_profile.invite_code, _external=True),
    )


@bp.route("/friends/<action>/<handle>", methods=["POST"])
@profile_required
def friend_action(action: str, handle: str):
    email = current_user_email()
    other = _other(handle)
    name = other.display_name
    if action == "request":
        rel = social.request_friend(email, other.user_email)
        flash(
            f"You and {name} are now friends."
            if rel == social.FRIENDS
            else f"Friend request sent to {name}.",
            "ok",
        )
    elif action == "accept":
        if social.accept(email, other.user_email):
            flash(f"You and {name} are now friends.", "ok")
    elif action in ("decline", "cancel", "remove"):
        social.unlink(email, other.user_email)
    else:
        abort(404)
    return redirect(_back(url_for("social.friends")))


@bp.route("/invite/<code>", methods=["GET", "POST"])
def invite(code: str):
    owner = social.profile_by_invite(code)
    if owner is None:
        abort(404)
    email = current_user_email()
    if email is None:
        session[AFTER_LOGIN] = url_for("social.invite", code=code)
        return render_template("invite.html", owner=owner, signed_in=False)
    if social.get_profile(email) is None:
        return redirect(url_for("social.profile_edit", next=url_for("social.invite", code=code)))
    rel = social.relationship(email, owner.user_email)
    if request.method == "POST" and rel not in (social.SELF, social.FRIENDS):
        social.befriend(email, owner.user_email)
        flash(f"You and {owner.display_name} are now friends.", "ok")
        return redirect(url_for("social.profile", handle=owner.handle))
    if rel in (social.SELF, social.FRIENDS):
        return redirect(url_for("social.profile", handle=owner.handle))
    return render_template("invite.html", owner=owner, signed_in=True)


# --- Feed, kudos and comments ------------------------------------------------------


@bp.route("/feed")
@profile_required
def feed():
    email = current_user_email()
    before = request.args.get("before")
    before = before if before and is_iso_date(before) else None
    cards, next_before = social.feed(email, before=before)
    return render_template(
        "feed.html",
        cards=cards,
        next_before=next_before,
        before=before,
        has_friends=bool(social.friend_emails(email)),
    )


def _session_or_404(handle: str, when: str):
    """The owner of a session the viewer may react to, or 404."""
    owner = _other(handle)
    if not is_iso_date(when) or not social.has_session(
        current_user_email(), owner.user_email, when
    ):
        abort(404)
    return owner


def card_anchor(owner_handle: str, when: str) -> str:
    return f"#s-{owner_handle}-{when}"


@bp.route("/kudos/<handle>/<when>", methods=["POST"])
@profile_required
def kudos(handle: str, when: str):
    owner = _session_or_404(handle, when)
    if owner.user_email == current_user_email():
        abort(404)  # kudos are for friends' sessions
    count, mine = social.toggle_kudos(current_user_email(), owner.user_email, when)
    if _wants_json():
        return jsonify(count=count, mine=mine)
    return redirect(_back(url_for("social.feed"), card_anchor(owner.handle, when)))


@bp.route("/comments/<handle>/<when>", methods=["POST"])
@profile_required
def comment(handle: str, when: str):
    owner = _session_or_404(handle, when)
    if (
        social.add_comment(
            current_user_email(), owner.user_email, when, request.form.get("body", "")
        )
        is None
    ):
        flash("Write something first.", "info")
    return redirect(_back(url_for("social.feed"), card_anchor(owner.handle, when)))


@bp.route("/comments/<int:comment_id>/delete", methods=["POST"])
@profile_required
def comment_delete(comment_id: int):
    c = social.delete_comment(current_user_email(), comment_id)
    if c is None:
        abort(404)
    owner = social.get_profile(c.owner_email)
    anchor = card_anchor(owner.handle, c.date) if owner else ""
    return redirect(_back(url_for("social.feed"), anchor))
