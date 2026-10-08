"""Progress and the day editor: the overview, the Sessions list, exercises, rest
days, and changing or removing one workout."""

from __future__ import annotations

from flask import jsonify, request

from .. import dayedit, preferences, rest, sessions, stats
from ..auth import current_user_email
from ..llm.client import BadOutputError
from ..logflow import MAX_ENTRIES
from ..parsing import is_iso_date, normalize_cardio, normalize_entry
from ..routes import (
    _client_today,
    exercise_parts,
    exercises_parts,
    progress_parts,
    sessions_parts,
)
from . import bp, schema
from .errors import ApiError, json_body, not_found, token_required

EDIT_STATUS = {"bad_date": 400}  # everything else an edit refuses is a 422


def _range() -> str:
    return stats.clean_range(request.args.get("range"))


@bp.route("/progress")
@token_required
def progress():
    """Mirrors routes.progress. ?week= is any date in the week the week card shows."""
    range_key = _range()
    by = stats.clean_grouping(request.args.get("by"), range_key)
    email = current_user_email()
    parts = progress_parts(email, _client_today(), range_key, by, request.args.get("week"))
    return jsonify(**schema.progress(parts), weight_unit=preferences.get_weight_unit(email))


@bp.route("/sessions")
@bp.route("/search")
@token_required
def session_list():
    """Mirrors routes.search: your workouts as cards under month headings. ?q= keeps
    the ones holding every word typed, as the search box on the page does."""
    range_key = _range()
    parts = sessions_parts(current_user_email(), _client_today(), range_key)
    words = request.args.get("q", "").lower().split()
    months, shown = [], 0
    for month in parts["months"]:
        days = [
            d
            for d in month["days"]
            if all(w in f"{d['search']} {d['date']} {month['label'].lower()}" for w in words)
        ]
        if days:
            shown += len(days)
            months.append(
                {
                    "key": month["key"],
                    "label": month["label"],
                    "days": [schema.session_tile(d) for d in days],
                }
            )
    return jsonify(range=range_key, months=months, shown=shown, total=parts["total"])


@bp.route("/exercises")
@token_required
def exercise_list():
    """Mirrors routes.exercises."""
    range_key = _range()
    parts = exercises_parts(current_user_email(), _client_today(), range_key)
    return jsonify(
        range=range_key,
        exercises=[schema.exercise_row(e) for e in parts["summary"]],
        cardio=[schema.cardio_row(c) for c in parts["cardio"]],
        total=parts["total"],
    )


@bp.route("/exercises/<path:name>")
@token_required
def exercise_detail(name: str):
    """Mirrors routes.exercise_history."""
    range_key = _range()
    email = current_user_email()
    parts = exercise_parts(email, name, _client_today(), range_key)
    if parts is None:
        raise not_found("You haven't logged that exercise.")
    return jsonify(
        **schema.exercise(parts), range=range_key, weight_unit=preferences.get_weight_unit(email)
    )


# --- Editing one workout --------------------------------------------------------


def _session_or_404(email: str, when: str, n: int):
    """The workout's records, or a 404 when nothing of it is logged."""
    if not is_iso_date(when):
        raise not_found("No such day.")
    lifts, cardio, weight = dayedit.records(email, when, n)
    first = dayedit.is_first(dayedit.other_sessions(email, when, n), n)
    if not (lifts or cardio or (weight and first)):
        raise not_found("Nothing is logged there.")
    return lifts, cardio


def _optional_text(data: dict, key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{key} must be text.")
    return value


def _row_edits(data: dict, key: str, fields, known: set[int], normalize):
    """`key` is a list of rows: one with an id changes (or with "delete": true,
    removes) a row of this workout; one without is a new row."""
    items = data.get(key) or []
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ApiError(400, "bad_request", f"{key} must be a list of objects.")
    changes: dict[int, dict | None] = {}
    added: list[dict] = []
    for item in items[:MAX_ENTRIES]:
        row_id = item.get("id")
        if row_id is None:
            try:
                row = normalize(item)
            except BadOutputError:
                raise ApiError(400, "bad_request", f"{key} holds a row we can't read.") from None
            if row[fields[0]]:
                added.append(row)
            continue
        if row_id not in known:
            raise ApiError(400, "bad_request", f"{key} names a row that isn't in this workout.")
        if item.get("delete"):
            changes[row_id] = None
            continue
        change = {}
        for name in fields:
            if name in item:
                if not isinstance(item[name], str):
                    raise ApiError(400, "bad_request", f"{name} must be text.")
                change[name] = item[name].strip()
        changes[row_id] = change
    return changes, added


def _edited(email: str, when: str, n: int, edit: dayedit.Edit):
    try:
        done = dayedit.apply(email, when, n, _client_today(), edit)
    except dayedit.EditError as e:
        raise ApiError(EDIT_STATUS.get(e.code, 422), e.code, e.message) from None
    return jsonify(
        date=done.date, session=done.session, removed=done.removed, weigh_in_left=done.weigh_in_left
    )


@bp.route("/day/<when>/sessions/<int:n>", methods=["PUT"])
@token_required
def session_update(when: str, n: int):
    """Mirrors routes.day_edit. Only what the body names changes: date, title,
    visibility, bodyweight (the day's first workout only), and rows in lifts / cardio."""
    email = current_user_email()
    lifts, cardio = _session_or_404(email, when, n)
    data = json_body()
    lift_changes, new_lifts = _row_edits(
        data, "lifts", dayedit.LIFT_FIELDS, {w.id for w in lifts}, normalize_entry
    )
    cardio_changes, new_cardio = _row_edits(
        data, "cardio", dayedit.CARDIO_FIELDS, {c.id for c in cardio}, normalize_cardio
    )
    edit = dayedit.Edit(
        date=_optional_text(data, "date") or "",
        title=_optional_text(data, "title"),
        visibility=_optional_text(data, "visibility"),
        bodyweight=_optional_text(data, "bodyweight"),
        lifts=lift_changes,
        cardio=cardio_changes,
        new_lifts=new_lifts,
        new_cardio=new_cardio,
    )
    return _edited(email, when, n, edit)


@bp.route("/day/<when>/sessions/<int:n>", methods=["DELETE"])
@token_required
def session_delete(when: str, n: int):
    """Remove one workout's lifts and cardio. The day's weigh-in stays."""
    email = current_user_email()
    lifts, cardio = _session_or_404(email, when, n)
    edit = dayedit.Edit(
        lifts=dict.fromkeys(w.id for w in lifts), cardio=dict.fromkeys(c.id for c in cardio)
    )
    return _edited(email, when, n, edit)


# --- Rest days -------------------------------------------------------------------


def _rules(email: str):
    return [schema.rest_rule(r) for r in sessions.rest_rules(email)]


@bp.route("/rest/rules", methods=["POST"])
@token_required
def rest_rule_add():
    """Mirrors routes.rest_rule_add: {"kind": "weekdays", "weekdays": [0, 6]} or
    {"kind": "interval", "interval_days": 4, "anchor_date": "2026-10-01"}."""
    data = json_body()
    days = data.get("weekdays") or []
    interval = data.get("interval_days")
    try:
        rest.add_rule(
            current_user_email(),
            data.get("kind") if isinstance(data.get("kind"), str) else "",
            weekdays=days if isinstance(days, list) else [],
            interval_days=interval if type(interval) is int else 0,
            anchor=stats.parse_date(data.get("anchor_date")) or _client_today(),
        )
    except ValueError as e:
        raise ApiError(422, "bad_rest_rule", str(e)) from None
    return jsonify(rest_rules=_rules(current_user_email())), 201


@bp.route("/rest/rules/<int:rule_id>", methods=["DELETE"])
@token_required
def rest_rule_delete(rule_id: int):
    """Mirrors routes.rest_rule_delete."""
    if not rest.delete_rule(current_user_email(), rule_id):
        raise not_found("No such rest rule.")
    return jsonify(rest_rules=_rules(current_user_email()))


@bp.route("/rest/day/<when>", methods=["PUT"])
@token_required
def rest_day_set(when: str):
    """Mirrors routes.rest_day_toggle: {"rest": true} or {"rest": false} sets the day
    by hand; an empty body flips it."""
    day = stats.parse_date(when)
    if day is None:
        raise not_found("No such day.")
    body = request.get_json(silent=True)
    wanted = body.get("rest") if isinstance(body, dict) else None
    if wanted is not None and not isinstance(wanted, bool):
        raise ApiError(400, "bad_request", "rest must be true or false.")
    try:
        is_rest = rest.set_day(current_user_email(), day, _client_today(), wanted)
    except ValueError as e:
        raise ApiError(422, "bad_rest_day", str(e)) from None
    return jsonify(date=when, rest=is_rest)
