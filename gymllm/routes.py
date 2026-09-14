"""All user-facing routes."""

from __future__ import annotations

import re
from datetime import date

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func

from .auth import current_user_email, login_required
from .exercises import llm_tags, match_exercise
from .extensions import db
from .llm.client import LLMError, test_connection
from .llm.providers import PROVIDERS, LLMConfig
from .models import FIELDS, Workout
from .parsing import is_iso_date, normalize_entry, parse_workout

bp = Blueprint("main", __name__)

ENTRY_FIELDS = ("exercise", "weight", "sets", "reps", "notes")
MAX_ENTRIES = 100
_CELL_RE = re.compile(r"^cell-(\d+)-(\w+)$")
_DELETE_RE = re.compile(r"^delete-(\d+)$")
_WEIGHT_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)")


def _llm_client():
    config = LLMConfig.from_session()
    if config is None or config.validate():
        return None, None
    return config, current_app.config["LLM_CLIENT_FACTORY"](config)


def _client_today() -> date:
    """Prefer the browser's local date (sent by app.js) over the server's."""
    value = request.form.get("client_date", "")
    if is_iso_date(value):
        return date.fromisoformat(value)
    return date.today()


def _is_local_host() -> bool:
    host = request.host.split(":")[0]
    return host in ("localhost", "127.0.0.1", "::1")


@bp.route("/healthz")
def healthz():
    return jsonify(ok=True)


@bp.route("/welcome")
def welcome():
    if current_user_email():
        return redirect(url_for("main.home"))
    return render_template("welcome.html")


@bp.route("/")
@login_required
def home():
    config = LLMConfig.from_session()
    if config is None:
        flash("Choose an LLM provider before logging a workout.", "info")
        return redirect(url_for("main.settings"))
    return render_template("log.html", config=config)


# --- Settings -----------------------------------------------------------------


def _config_from_form(form) -> LLMConfig:
    provider = form.get("provider", "openai")
    if provider not in PROVIDERS:
        provider = "openai"
    existing = LLMConfig.from_session()
    api_key = form.get("api_key", "").strip()
    if not api_key and existing and existing.provider == provider:
        api_key = existing.api_key  # keep the saved key when the field is left blank
    return LLMConfig(
        provider=provider,
        model=form.get("model", "").strip() or PROVIDERS[provider].default_model,
        api_key=api_key,
        base_url=form.get("base_url", "").strip(),
    )


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        config = _config_from_form(request.form)
        errors = config.validate()
        if errors:
            for e in errors:
                flash(e, "error")
            return (
                render_template("settings.html", config=config, is_local_host=_is_local_host()),
                400,
            )
        config.to_session()
        flash(f"Saved. Using {config.describe()}.", "ok")
        return redirect(url_for("main.settings"))
    config = LLMConfig.from_session() or LLMConfig(
        provider="openai", model=PROVIDERS["openai"].default_model
    )
    return render_template("settings.html", config=config, is_local_host=_is_local_host())


@bp.route("/settings/test", methods=["POST"])
@login_required
def settings_test():
    config = _config_from_form(request.form)
    errors = config.validate()
    if errors:
        return jsonify(ok=False, message=" ".join(errors)), 400
    client = current_app.config["LLM_CLIENT_FACTORY"](config)
    ok, message = test_connection(config, client=client)
    return jsonify(ok=ok, message=message)


# --- Logging flow -------------------------------------------------------------


@bp.route("/review", methods=["POST"])
@login_required
def review():
    workout_text = request.form.get("workout", "").strip()
    if not workout_text:
        flash("Describe your workout first.", "error")
        return redirect(url_for("main.home"))
    config, client = _llm_client()
    if client is None:
        flash("Set up an LLM provider first.", "error")
        return redirect(url_for("main.settings"))

    today = _client_today()
    context = {"workout_text": workout_text, "client_date": today.isoformat()}
    try:
        parsed = parse_workout(workout_text, client, today=today)
    except LLMError as e:
        return render_template("review.html", error=e.user_message, entries=None, **context)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Unexpected error while parsing workout")
        return render_template(
            "review.html",
            error="Something went wrong while talking to the model. Please try again.",
            entries=None,
            **context,
        )
    return render_template(
        "review.html",
        error=None,
        entries=parsed.entries,
        workout_date=parsed.date or today.isoformat(),
        date_from_text=parsed.date is not None,
        **context,
    )


def _entries_from_form(form) -> list[dict]:
    try:
        count = min(int(form.get("num_entries", 0)), MAX_ENTRIES)
    except ValueError:
        count = 0
    entries = []
    for i in range(count):
        if form.get(f"entry-{i}-delete"):
            continue
        raw = {f: form.get(f"entry-{i}-{f}", "") for f in ENTRY_FIELDS}
        entry = normalize_entry(raw)
        if entry["exercise"]:
            entries.append(entry)
    return entries


@bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    user_email = current_user_email()
    when = request.form.get("date", "").strip()
    if not is_iso_date(when):
        flash("Date must be in YYYY-MM-DD format.", "error")
        return redirect(url_for("main.home"))
    entries = _entries_from_form(request.form)
    if not entries:
        flash("Nothing to save: every row was empty or deleted.", "error")
        return redirect(url_for("main.home"))

    _config, client = _llm_client()
    saved = []
    for entry in entries:
        match = match_exercise(entry["exercise"])
        if match:
            name, tags = match
        else:
            name = entry["exercise"]
            tags = llm_tags(name, client) if client else ""
        workout = Workout(
            user_email=user_email,
            date=when,
            exercise=name,
            weight=entry["weight"],
            sets=entry["sets"],
            reps=entry["reps"],
            notes=entry["notes"],
            tags=tags,
        )
        db.session.add(workout)
        saved.append(workout)
    db.session.commit()
    return render_template("saved.html", rows=[w.as_dict() for w in saved], workout_date=when)


# --- Search / edit ------------------------------------------------------------


@bp.route("/search", methods=["GET", "POST"])
@login_required
def search():
    user_email = current_user_email()
    if request.method == "POST":
        return _apply_search_edits(user_email)
    workouts = (
        Workout.query.filter_by(user_email=user_email)
        .order_by(Workout.date.desc(), Workout.id.desc())
        .all()
    )
    return render_template("search.html", rows=[w.as_dict() for w in workouts], fields=FIELDS)


def _apply_search_edits(user_email: str):
    edits: dict[int, dict[str, str]] = {}
    deletes: set[int] = set()
    for key, value in request.form.items():
        m = _CELL_RE.match(key)
        if m and m.group(2) in FIELDS:
            edits.setdefault(int(m.group(1)), {})[m.group(2)] = value.strip()
            continue
        m = _DELETE_RE.match(key)
        if m and value:
            deletes.add(int(m.group(1)))

    ids = set(edits) | deletes
    if not ids:
        return redirect(url_for("main.search"))
    rows = Workout.query.filter(Workout.user_email == user_email, Workout.id.in_(ids)).all()
    by_id = {w.id: w for w in rows}

    bad_dates = [
        wid
        for wid, cells in edits.items()
        if wid in by_id
        and wid not in deletes
        and "date" in cells
        and not is_iso_date(cells["date"])
    ]
    if bad_dates:
        flash("Dates must be in YYYY-MM-DD format. No changes were saved.", "error")
        return redirect(url_for("main.search"))

    deleted = changed = 0
    for wid, workout in by_id.items():
        if wid in deletes:
            db.session.delete(workout)
            deleted += 1
            continue
        cells = edits.get(wid, {})
        if "exercise" in cells and not cells["exercise"]:
            cells.pop("exercise")  # never blank the exercise name
        dirty = False
        for field_name, value in cells.items():
            if (getattr(workout, field_name) or "") != value:
                setattr(workout, field_name, value)
                dirty = True
        changed += dirty
    db.session.commit()
    if deleted or changed:
        flash(f"Saved: {changed} updated, {deleted} deleted.", "ok")
    else:
        flash("No changes to save.", "info")
    return redirect(url_for("main.search"))


# --- History ------------------------------------------------------------------


def _weight_number(weight: str | None) -> float | None:
    m = _WEIGHT_NUM_RE.match(weight or "")
    return float(m.group(1)) if m else None


@bp.route("/exercises")
@login_required
def exercises():
    user_email = current_user_email()
    rows = (
        db.session.query(
            Workout.exercise,
            func.count(Workout.id),
            func.max(Workout.date),
            func.min(Workout.date),
        )
        .filter(Workout.user_email == user_email)
        .group_by(Workout.exercise)
        .order_by(func.max(Workout.date).desc(), Workout.exercise)
        .all()
    )
    summary = [
        {"exercise": ex, "sessions": count, "last": last, "first": first}
        for ex, count, last, first in rows
    ]
    return render_template("exercises.html", summary=summary)


@bp.route("/exercise/<path:name>")
@login_required
def exercise_history(name: str):
    user_email = current_user_email()
    target = name.strip().lower()
    if not target:
        abort(404)
    workouts = (
        Workout.query.filter(
            Workout.user_email == user_email,
            func.lower(Workout.exercise) == target,
        )
        .order_by(Workout.date.asc(), Workout.id.asc())
        .all()
    )
    rows = [w.as_dict() for w in workouts]

    best = None
    per_date: dict[str, float] = {}
    for w in workouts:
        n = _weight_number(w.weight)
        if n is None:
            continue
        per_date[w.date] = max(per_date.get(w.date, 0.0), n)
        if best is None or n > best["value"]:
            best = {"value": n, "weight": w.weight, "date": w.date}
    series = [{"date": d, "weight": per_date[d]} for d in sorted(per_date)]
    tags = next((w.tags for w in workouts if w.tags), "")

    return render_template(
        "exercise.html",
        name=target,
        rows=rows,
        sessions=len({w.date for w in workouts}),
        best=best,
        last_date=workouts[-1].date if workouts else None,
        tags=tags,
        series=series,
    )
