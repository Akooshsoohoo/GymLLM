"""The rest of the app: routines for the recorder, the names the manual form
suggests, hiding the getting-started checklist, and who may see a day."""

from __future__ import annotations

from flask import jsonify

from .. import preferences, routines, social
from ..auth import current_user_email
from ..exercises import ACTIVITY_NAMES, EXERCISE_NAMES
from ..extensions import db
from ..models import Cardio, Workout
from ..parsing import is_iso_date
from . import bp, schema
from .errors import ApiError, json_body, not_found, token_required

# --- Routines -------------------------------------------------------------------


def _routine_or_404(routine_id: int):
    """One of your own routines. Somebody else's is simply not found."""
    routine = routines.get(current_user_email(), routine_id)
    if routine is None:
        raise not_found("No such routine.")
    return routine


def _routine_body() -> tuple[str, list[dict]]:
    """The name and blocks an editor sent: {"name": ..., "blocks": [{"name", "body"}]}.
    Cleaned as routes._routine_editor cleans the form; only a blank name is refused."""
    data = json_body()
    raw_name = data.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        raise ApiError(400, "bad_request", "name must be text.")
    blocks = data.get("blocks") or []
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        raise ApiError(400, "bad_request", "blocks must be a list of objects.")
    names, bodies = [], []
    for block in blocks:
        for key, into in (("name", names), ("body", bodies)):
            value = block.get(key) or ""
            if not isinstance(value, str):
                raise ApiError(400, "bad_request", f"A block's {key} must be text.")
            into.append(value)
    name, error = routines.validate(raw_name)
    if error:
        raise ApiError(422, "bad_routine", error)
    return name, routines.clean_blocks(names, bodies)


@bp.route("/routines")
@token_required
def routine_list():
    """Mirrors routes.routine_list: most recently changed first, with block counts."""
    return jsonify(
        routines=[schema.routine_row(r) for r in routines.list_for(current_user_email())]
    )


@bp.route("/routines", methods=["POST"])
@token_required
def routine_create():
    """Mirrors routes.routine_new."""
    name, blocks = _routine_body()
    routine = routines.create(current_user_email(), name, blocks)
    db.session.commit()
    return jsonify(schema.routine(routine, routines.blocks_of(routine))), 201


@bp.route("/routines/<int:routine_id>")
@token_required
def routine_detail(routine_id: int):
    """A routine with its blocks: what the editor opens on, and what the recorder
    starts from (routes.record with ?routine=)."""
    routine = _routine_or_404(routine_id)
    return jsonify(schema.routine(routine, routines.blocks_of(routine)))


@bp.route("/routines/<int:routine_id>", methods=["PUT"])
@token_required
def routine_update(routine_id: int):
    """Mirrors routes.routine_edit: the name and the blocks are replaced wholesale."""
    routine = _routine_or_404(routine_id)
    name, blocks = _routine_body()
    routines.update(routine, name, blocks)
    db.session.commit()
    return jsonify(schema.routine(routine, routines.blocks_of(routine)))


@bp.route("/routines/<int:routine_id>", methods=["DELETE"])
@token_required
def routine_delete(routine_id: int):
    """Mirrors routes.routine_delete. Workouts logged with it stay as they are."""
    routines.delete(_routine_or_404(routine_id))
    db.session.commit()
    return jsonify(
        routines=[schema.routine_row(r) for r in routines.list_for(current_user_email())]
    )


# --- Manual entry ---------------------------------------------------------------


@bp.route("/log/manual")
@token_required
def log_manual():
    """Mirrors routes.log_manual: the names its form suggests as you type. The form
    itself saves through POST /sessions, as the page posts to routes.confirm."""
    return jsonify(exercises=[n.title() for n in EXERCISE_NAMES], activities=list(ACTIVITY_NAMES))


# --- The getting-started checklist ----------------------------------------------


@bp.route("/onboarding/dismiss", methods=["POST"])
@token_required
def onboarding_dismiss():
    """Mirrors routes.onboarding_dismiss: Home's checklist is hidden for good."""
    preferences.dismiss_onboarding(current_user_email())
    return jsonify(checklist=None)


# --- Who may see a day ----------------------------------------------------------


@bp.route("/day/<when>/visibility", methods=["PUT"])
@token_required
def day_visibility(when: str):
    """Set who may see one of your days: {"visibility": "private" | "friends"}. It
    covers every workout of the day, as the choice on the day editor does."""
    if not is_iso_date(when):
        raise not_found("No such day.")
    visibility = json_body().get("visibility")
    if visibility not in (social.PRIVATE, social.FRIENDS_ONLY):
        raise ApiError(400, "bad_request", "visibility must be private or friends.")
    email = current_user_email()
    # A weigh-in is always private, so a day with only that has nothing to set.
    if not any(
        db.session.query(model.id).filter_by(user_email=email, date=when).first() is not None
        for model in (Workout, Cardio)
    ):
        raise not_found("Nothing is logged there.")
    social.set_visibility(email, when, visibility)
    db.session.commit()
    return jsonify(date=when, visibility=visibility)
