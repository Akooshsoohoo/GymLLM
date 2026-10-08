"""The core loop: who you are, Home, parse, save, one day, and preferences."""

from __future__ import annotations

from flask import current_app, jsonify, request

from .. import (
    _first_name,
    auth,
    dayedit,
    logflow,
    preferences,
    quota,
    routines,
    session_meta,
    social,
    stats,
)
from .. import sessions as sessions_mod
from ..auth import current_user_email
from ..llm.client import BadOutputError
from ..llm.providers import LLMConfig
from ..parsing import is_iso_date, normalize_cardio, normalize_entry, parse_workout
from ..routes import _client_today, _has_logged, day_parts, home_parts
from . import bp, schema
from .errors import ApiError, json_body, not_found, token_required

# What the app says when a log can't be read. The web's own messages point at
# Settings, keys and models, none of which the app has.
PARSE_ERRORS = {
    logflow.QUOTA_EXCEEDED: (
        429,
        "You've used today's {limit} free logs. Come back tomorrow, or add this one by hand.",
    ),
    logflow.RATE_LIMITED: (503, "Levra is busy right now. Try again in a minute."),
    logflow.BAD_OUTPUT: (422, "We couldn't make sense of that. Try saying it another way."),
    logflow.MODEL_ERROR: (502, "Something went wrong on our side. Please try again."),
}
SAVE_STATUS = {"bad_date": 400}  # everything else a save refuses is a 422


def _site_config() -> LLMConfig | None:
    """The shared model, the only one the app logs with, or None if it isn't set up."""
    config = LLMConfig.site_default()
    return config if config is not None and not config.validate() else None


def _quota(user_email: str) -> dict | None:
    if _site_config() is None:
        return None
    limit = logflow.site_limit()
    return {"left": quota.remaining(user_email, limit), "limit": limit}


def _token_name() -> str:
    claims, _ = auth.api_token_claims()
    return (claims or {}).get("name") or ""


def me_payload(email: str, google_name: str) -> dict:
    profile = social.get_profile(email)
    return {
        "email": email,
        "first_name": _first_name(email, profile, google_name),
        "profile": schema.own_profile(profile),
        "weight_unit": preferences.get_weight_unit(email),
        "quota": _quota(email),
        "unseen": social.unseen_count(email) if profile else 0,
    }


@bp.route("/me")
@token_required
def me():
    return jsonify(me_payload(current_user_email(), _token_name()))


@bp.route("/home")
@token_required
def home():
    """Mirrors routes.home. ?saved= and ?session= name the workout just logged."""
    email = current_user_email()
    today = _client_today()
    rows, cardio, weights = (
        sessions_mod.all_rows(email),
        sessions_mod.all_cardio(email),
        sessions_mod.all_weights(email),
    )
    week = stats.week_strip(
        today,
        rows,
        cardio,
        weights,
        rest_rules=sessions_mod.rest_rules(email),
        rest_overrides=sessions_mod.rest_overrides(email),
    )
    parts = home_parts(
        email,
        today.isoformat(),
        (rows, cardio, weights),
        request.args.get("saved", ""),
        request.args.get("session", type=int),
    )
    return jsonify(
        today=today.isoformat(),
        week=[schema.week_day(d) for d in week],
        streak=stats.week_streak({x["date"] for x in rows + cardio}, today),
        latest=schema.my_card(parts["latest"]),
        just_saved=parts["just_saved"],
        first_save=parts["first_save"],
        has_logged=parts["has_logged"],
        recent=[schema.recent(s) for s in parts["recent"]],
        friends=[schema.friend_card(c) for c in parts["friend_cards"]],
        has_friends=parts["has_friends"],
        checklist=parts["checklist"],
        quota=_quota(email),
    )


@bp.route("/parse", methods=["POST"])
@token_required
def parse():
    """Mirrors routes.review: plain English in, entries to check over out."""
    data = json_body()
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "empty_text", "Describe your workout first.")
    config = _site_config()
    if config is None:
        raise ApiError(503, "logging_unavailable", "Logging isn't available right now.")
    email = current_user_email()
    today = _client_today()
    if data.get("weight_unit") in preferences.UNITS:
        unit = preferences.set_weight_unit(email, data["weight_unit"])
    else:
        unit = preferences.get_weight_unit(email)

    def run():
        client = current_app.config["LLM_CLIENT_FACTORY"](config.resolved())
        return parse_workout(text.strip(), client, today=today, default_unit=unit)

    try:
        parsed = logflow.parse(email, config, run)
    except logflow.LogError as e:
        status, message = PARSE_ERRORS[e.code]
        raise ApiError(status, e.code, message.format(limit=logflow.site_limit())) from None
    when = parsed.date or today.isoformat()
    routine_name = data.get("routine_name")
    return jsonify(
        date=when,
        date_from_text=parsed.date is not None,
        entries=[schema.parsed_entry(e) for e in parsed.entries],
        cardio=[schema.parsed_cardio(c) for c in parsed.cardio],
        bodyweight=parsed.bodyweight,
        # A workout started from a routine takes the routine's name.
        title=routines.clean_title(routine_name if isinstance(routine_name, str) else None),
        default_title=session_meta.default_title(when),
        # Nobody to share with yet: start private until there's a profile.
        visibility=social.FRIENDS_ONLY if social.get_profile(email) else social.PRIVATE,
        first_log=not _has_logged(email),
        weight_unit=unit,
        quota=_quota(email),
    )


def _rows(data: dict, key: str, normalize) -> list[dict]:
    """A list of entry objects from the request body, normalised like the model's."""
    raw = data.get(key) or []
    if not isinstance(raw, list):
        raise ApiError(400, "bad_request", f"{key} must be a list.")
    try:
        return [normalize(item) for item in raw[: logflow.MAX_ENTRIES]]
    except BadOutputError:
        raise ApiError(400, "bad_request", f"Every item in {key} must be an object.") from None


def _text(data: dict, key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{key} must be text.")
    return value.strip()


@bp.route("/sessions", methods=["POST"])
@token_required
def session_create():
    """Mirrors routes.confirm: save what was reviewed as a new workout."""
    data = json_body()
    entries = [e for e in _rows(data, "entries", normalize_entry) if e["exercise"]]
    cardio = [c for c in _rows(data, "cardio", normalize_cardio) if c["activity"]]
    config = _site_config()
    get_client = None
    if config is not None:

        def get_client():
            return current_app.config["LLM_CLIENT_FACTORY"](config.resolved())

    email = current_user_email()
    when = _text(data, "date")
    try:
        n = logflow.save(
            email,
            when,
            _client_today(),
            entries,
            cardio,
            _text(data, "bodyweight"),
            visibility=_text(data, "visibility"),
            title=_text(data, "title"),
            get_client=get_client,
            tag_calls=logflow.MAX_SITE_TAG_CALLS,
        )
    except logflow.LogError as e:
        raise ApiError(SAVE_STATUS.get(e.code, 422), e.code, e.message) from None
    return jsonify(date=when, session=n), 201


@bp.route("/day/<when>")
@token_required
def day(when: str):
    """Mirrors routes.day: one of your own workouts on a day (?session= picks it)."""
    if not is_iso_date(when):
        raise not_found("No such day.")
    email = current_user_email()
    parts = day_parts(email, when, request.args.get("session", type=int))
    n = parts["n"]
    return jsonify(
        **schema.day(parts),
        # What the editor starts from, beside the lifts and cardio above.
        default_title=session_meta.default_title(when, n),
        visibility=social.visibilities(email).get(when, social.FRIENDS_ONLY),
        edits_bodyweight=dayedit.is_first(dayedit.other_sessions(email, when, n), n),
    )


@bp.route("/preferences", methods=["PUT"])
@token_required
def preferences_update():
    """Mirrors routes.weight_unit."""
    unit = json_body().get("weight_unit")
    if unit not in preferences.UNITS:
        raise ApiError(400, "bad_request", "weight_unit must be lbs or kg.")
    return jsonify(weight_unit=preferences.set_weight_unit(current_user_email(), unit))


@bp.route("/", defaults={"_path": ""})
@bp.route("/<path:_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def unknown(_path: str):
    """Anything else under /api/v1 gets a JSON 404, not the site's HTML one."""
    raise not_found()
