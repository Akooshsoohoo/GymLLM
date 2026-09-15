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

from . import quota, stats
from .auth import current_user_email, login_required
from .exercises import TAG_SYSTEM, clean_tags, llm_tags, match_exercise
from .extensions import db
from .llm.client import (
    BadOutputError,
    LLMError,
    RateLimitError,
    extract_json,
    test_connection,
)
from .llm.providers import PROVIDERS, LLMConfig
from .models import FIELDS, Workout
from .parsing import (
    build_system_prompt,
    is_iso_date,
    normalize_entry,
    parse_workout,
    parsed_from_output,
)

bp = Blueprint("main", __name__)

ENTRY_FIELDS = ("exercise", "weight", "sets", "reps", "notes")
MAX_ENTRIES = 100
MAX_LLM_OUTPUT = 200_000
MAX_SITE_TAG_CALLS = 10  # per save, so tagging cannot drain the shared allowance
RECENT_SESSIONS = 5
_CELL_RE = re.compile(r"^cell-(\d+)-(\w+)$")
_DELETE_RE = re.compile(r"^delete-(\d+)$")


def _llm_config() -> LLMConfig | None:
    """The saved, valid provider config, or None if the user still has to set one up.

    With no saved choice the site's shared model (if configured) is used, so a
    new user can log a workout without ever visiting Settings."""
    config = LLMConfig.from_session() or LLMConfig.site_default()
    if config is None or config.validate():
        return None
    return config


def _site_limit() -> int:
    return int((LLMConfig.site_settings() or {}).get("daily_limit", 0))


def _llm_client(config: LLMConfig):
    """A server-side client, or None when the provider is called from the browser."""
    if config.runs_in_browser:
        return None
    return current_app.config["LLM_CLIENT_FACTORY"](config.resolved())


def _client_today() -> date:
    """Prefer the browser's local date (sent by app.js) over the server's."""
    value = request.form.get("client_date", "") or request.args.get("today", "")
    if is_iso_date(value):
        return date.fromisoformat(value)
    return date.today()


def _period_args() -> tuple[str, str, date]:
    """The `range` and `by` query params, validated, plus the reference 'today'."""
    range_key = stats.clean_range(request.args.get("range"))
    by = stats.clean_grouping(request.args.get("by"), range_key)
    return range_key, by, _client_today()


def _all_rows(user_email: str) -> list[dict]:
    workouts = (
        Workout.query.filter_by(user_email=user_email)
        .order_by(Workout.date.desc(), Workout.id.desc())
        .all()
    )
    return [w.as_dict() for w in workouts]


def _site_origin() -> str:
    return request.host_url.rstrip("/")


@bp.route("/healthz")
def healthz():
    return jsonify(ok=True)


@bp.route("/welcome")
def welcome():
    if current_user_email():
        return redirect(url_for("main.home"))
    return render_template("welcome.html")


def _sets_summary(sets: str, reps: str) -> str:
    """Compact 'sets x reps' for the session cards: '5, 5, 5' with 3 sets -> '3x5'."""
    parts = [r.strip() for r in reps.split(",") if r.strip()]
    if parts and len(set(parts)) == 1 and (not sets or sets == str(len(parts))):
        return f"{len(parts)}×{parts[0]}"
    if sets and reps:
        return f"{sets}×{reps}"
    return sets or reps


def _recent_sessions(user_email: str, limit: int = RECENT_SESSIONS) -> list[dict]:
    """The user's most recent workout days, newest first, each with its entries."""
    workouts = (
        Workout.query.filter_by(user_email=user_email)
        .order_by(Workout.date.desc(), Workout.id.desc())
        .all()
    )
    sessions: list[dict] = []
    for w in workouts:
        if not sessions or sessions[-1]["date"] != w.date:
            if len(sessions) == limit:
                break
            sessions.append({"date": w.date, "rows": []})
        row = w.as_dict()
        row["sets_reps"] = _sets_summary(row["sets"], row["reps"])
        sessions[-1]["rows"].append(row)
    return sessions


@bp.route("/")
@login_required
def home():
    config = _llm_config()
    if config is None:
        flash("Choose an LLM provider before logging a workout.", "info")
        return redirect(url_for("main.settings"))
    user_email = current_user_email()
    quota_left = quota_limit = None
    if config.is_site:
        quota_limit = _site_limit()
        quota_left = quota.remaining(user_email, quota_limit)
    return render_template(
        "log.html",
        config=config,
        sessions=_recent_sessions(user_email),
        quota_left=quota_left,
        quota_limit=quota_limit,
    )


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
                render_template("settings.html", config=config, site_origin=_site_origin()),
                400,
            )
        config.to_session()
        flash(f"Saved. Using {config.describe()}.", "ok")
        return redirect(url_for("main.settings"))
    config = (
        LLMConfig.from_session()
        or LLMConfig.site_default()
        or LLMConfig(provider="openai", model=PROVIDERS["openai"].default_model)
    )
    return render_template("settings.html", config=config, site_origin=_site_origin())


@bp.route("/settings/test", methods=["POST"])
@login_required
def settings_test():
    config = _config_from_form(request.form)
    errors = config.validate()
    if errors:
        return jsonify(ok=False, message=" ".join(errors)), 400
    if config.runs_in_browser:
        return jsonify(ok=False, message="This provider is tested from your browser."), 400
    client = current_app.config["LLM_CLIENT_FACTORY"](config.resolved())
    ok, message = test_connection(config, client=client)
    return jsonify(ok=ok, message=message)


# --- Browser-side LLM helpers -------------------------------------------------
# Local providers (Ollama, LM Studio) are called by page JavaScript, so these
# endpoints hand the page the same prompts the server would have used.


@bp.route("/llm/prompt")
@login_required
def llm_prompt():
    when = request.args.get("date", "")
    if not is_iso_date(when):
        return jsonify(error="date must be YYYY-MM-DD"), 400
    return jsonify(system=build_system_prompt(date.fromisoformat(when)))


@bp.route("/llm/tag-targets", methods=["POST"])
@login_required
def llm_tag_targets():
    data = request.get_json(silent=True) or {}
    names = data.get("names")
    if not isinstance(names, list):
        return jsonify(error="names must be a list"), 400
    unmatched: list[str] = []
    for raw in names[:MAX_ENTRIES]:
        name = str(raw or "").strip()
        if name and match_exercise(name) is None and name not in unmatched:
            unmatched.append(name)
    return jsonify(unmatched=unmatched, system=TAG_SYSTEM)


# --- Logging flow -------------------------------------------------------------


@bp.route("/review", methods=["POST"])
@login_required
def review():
    workout_text = request.form.get("workout", "").strip()
    if not workout_text:
        flash("Describe your workout first.", "error")
        return redirect(url_for("main.home"))
    config = _llm_config()
    if config is None:
        flash("Set up an LLM provider first.", "error")
        return redirect(url_for("main.settings"))

    today = _client_today()
    context = {"workout_text": workout_text, "client_date": today.isoformat(), "config": config}
    if config.is_site:
        limit = _site_limit()
        if not quota.consume(current_user_email(), limit):
            return render_template(
                "review.html",
                error=(
                    f"You have used today's {limit} free parses with the shared model. "
                    "Come back tomorrow, or add your own key or a local model on the "
                    "Settings page."
                ),
                entries=None,
                **context,
            )
    try:
        if config.runs_in_browser:
            parsed = _parse_browser_output(request.form.get("llm_output", ""))
        else:
            parsed = parse_workout(workout_text, _llm_client(config), today=today)
    except RateLimitError as e:
        message = e.user_message
        if config.is_site:
            message = (
                "The shared model is busy or its daily allowance is used up. Try again in a "
                "minute, or use your own key on the Settings page."
            )
        return render_template("review.html", error=message, entries=None, **context)
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


def _parse_browser_output(raw: str):
    """Validate the model response the page fetched from a local provider."""
    raw = (raw or "").strip()
    if not raw:
        raise BadOutputError(
            "Your browser did not return a model response. JavaScript must be enabled "
            "to use a local model."
        )
    if len(raw) > MAX_LLM_OUTPUT:
        raise BadOutputError("The model response was too large to process.")
    return parsed_from_output(extract_json(raw))


def _entries_from_form(form, with_tags: bool = False) -> list[dict]:
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
            if with_tags:
                entry["tags"] = clean_tags(form.get(f"entry-{i}-tags", ""))
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
    config = _llm_config()
    in_browser = config is not None and config.runs_in_browser
    entries = _entries_from_form(request.form, with_tags=in_browser)
    if not entries:
        flash("Nothing to save: every row was empty or deleted.", "error")
        return redirect(url_for("main.home"))

    client = _llm_client(config) if config else None
    tag_calls_left = MAX_SITE_TAG_CALLS if config is not None and config.is_site else MAX_ENTRIES
    saved = []
    for entry in entries:
        match = match_exercise(entry["exercise"])
        if match:
            name, tags = match
        elif in_browser:
            name = entry["exercise"]
            tags = entry.get("tags", "")  # tagged by the local model in the browser
        else:
            name = entry["exercise"]
            tags = ""
            if client and tag_calls_left > 0:
                tag_calls_left -= 1
                tags = llm_tags(name, client)
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
    range_key = stats.clean_range(request.args.get("range"))
    by = stats.clean_grouping(request.args.get("by"), "7d")  # entries default to per-day
    all_rows = _all_rows(user_email)
    rows = stats.filter_range(all_rows, _client_today(), range_key)
    return render_template(
        "search.html",
        groups=stats.group_rows(rows, by),
        total=len(all_rows),
        shown=len(rows),
        range_key=range_key,
        by=by,
        fields=FIELDS,
    )


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
    keep = {k: v for k, v in request.args.items() if k in ("range", "by")}
    return redirect(url_for("main.search", **keep))


# --- Progress -----------------------------------------------------------------


@bp.route("/progress")
@login_required
def progress():
    range_key, by, today = _period_args()
    all_rows = _all_rows(current_user_email())
    data = stats.overview(all_rows, today, range_key, by)
    return render_template(
        "progress.html", data=data, total=len(all_rows), range_key=range_key, by=by
    )


@bp.route("/exercises")
@login_required
def exercises():
    range_key = stats.clean_range(request.args.get("range"))
    all_rows = _all_rows(current_user_email())
    rows = stats.filter_range(all_rows, _client_today(), range_key)
    per_ex: dict[str, list[dict]] = {}
    for r in rows:
        per_ex.setdefault(r["exercise"], []).append(r)
    summary = []
    for name, members in per_ex.items():
        series = stats.exercise_series(members)
        weighted = [r for r in members if stats.weight_number(r["weight"]) is not None]
        best = max(weighted, key=lambda r: stats.weight_number(r["weight"]), default=None)
        summary.append(
            {
                "exercise": name,
                "entries": len(members),
                "sessions": len(series),
                "first": series[0]["date"],
                "last": series[-1]["date"],
                "best": best["weight"] if best else "",
                "spark": [p["weight"] for p in series if p["weight"] is not None][-12:],
            }
        )
    summary.sort(key=lambda s: (s["last"], s["exercise"]), reverse=True)
    return render_template(
        "exercises.html", summary=summary, total=len(all_rows), range_key=range_key
    )


@bp.route("/exercise/<path:name>")
@login_required
def exercise_history(name: str):
    user_email = current_user_email()
    target = name.strip().lower()
    if not target:
        abort(404)
    range_key = stats.clean_range(request.args.get("range"))
    workouts = (
        Workout.query.filter(
            Workout.user_email == user_email,
            func.lower(Workout.exercise) == target,
        )
        .order_by(Workout.date.asc(), Workout.id.asc())
        .all()
    )
    all_rows = [w.as_dict() for w in workouts]
    rows = stats.filter_range(all_rows, _client_today(), range_key)
    series = stats.exercise_series(rows)

    best = None
    for r in rows:
        n = stats.weight_number(r["weight"])
        if n is not None and (best is None or n > best["value"]):
            best = {"value": n, "weight": r["weight"], "date": r["date"]}
    volume = sum(p["volume"] for p in series)
    tags = next((r["tags"] for r in all_rows if r["tags"]), "")

    return render_template(
        "exercise.html",
        name=target,
        rows=list(reversed(rows)),
        total=len(all_rows),
        sessions=len(series),
        best=best,
        volume=volume,
        last_date=rows[-1]["date"] if rows else None,
        tags=tags,
        series=series,
        range_key=range_key,
    )
