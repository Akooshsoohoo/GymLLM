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
from .models import BODYWEIGHT_FIELDS, CARDIO_FIELDS, FIELDS, BodyWeight, Cardio, Workout
from .parsing import (
    build_system_prompt,
    is_iso_date,
    normalize_cardio,
    normalize_entry,
    parse_workout,
    parsed_from_output,
)

bp = Blueprint("main", __name__)

ENTRY_FIELDS = ("exercise", "weight", "sets", "reps", "notes")
CARDIO_FORM_FIELDS = ("activity", "distance", "duration", "notes")
MAX_ENTRIES = 100
MAX_LLM_OUTPUT = 200_000
MAX_SITE_TAG_CALLS = 10  # per save, so tagging cannot drain the shared allowance
RECENT_SESSIONS = 5

# Editable tables on the Sessions page: (model, cell name regex, delete regex,
# editable fields, the field that may never be blanked).
EDITABLE = (
    (Workout, re.compile(r"^cell-(\d+)-(\w+)$"), re.compile(r"^delete-(\d+)$"), FIELDS, "exercise"),
    (
        Cardio,
        re.compile(r"^cardio-(\d+)-(\w+)$"),
        re.compile(r"^cdelete-(\d+)$"),
        CARDIO_FIELDS,
        "activity",
    ),
    (
        BodyWeight,
        re.compile(r"^bw-(\d+)-(\w+)$"),
        re.compile(r"^bwdelete-(\d+)$"),
        BODYWEIGHT_FIELDS,
        "weight",
    ),
)


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


def _all_of(model, user_email: str) -> list[dict]:
    """Every row of `model` for the user as dicts, newest first."""
    rows = (
        model.query.filter_by(user_email=user_email)
        .order_by(model.date.desc(), model.id.desc())
        .all()
    )
    return [r.as_dict() for r in rows]


def _all_rows(user_email: str) -> list[dict]:
    return _all_of(Workout, user_email)


def _all_cardio(user_email: str) -> list[dict]:
    return _all_of(Cardio, user_email)


def _all_weights(user_email: str) -> list[dict]:
    return _all_of(BodyWeight, user_email)


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
    """The user's most recent days with anything logged, newest first, each with
    its strength entries, cardio, and weigh-in."""
    rows = _all_rows(user_email)
    cardio = _all_cardio(user_email)
    weights = _all_weights(user_email)
    dates = {r["date"] for r in rows} | {c["date"] for c in cardio} | {w["date"] for w in weights}
    sessions = []
    for day in sorted(dates, reverse=True)[:limit]:
        strength = [
            dict(r, sets_reps=_sets_summary(r["sets"], r["reps"])) for r in rows if r["date"] == day
        ]
        sessions.append(
            {
                "date": day,
                "rows": strength,
                "cardio": [c for c in cardio if c["date"] == day],
                "weight": next((w for w in weights if w["date"] == day), None),
            }
        )
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


# --- One day ------------------------------------------------------------------


def _neighbours(dates: set[str], when: str) -> tuple[str | None, str | None]:
    """The nearest logged dates before and after `when` (either may be None)."""
    before = [d for d in dates if d < when]
    after = [d for d in dates if d > when]
    return (max(before) if before else None, min(after) if after else None)


@bp.route("/day/<when>")
@login_required
def day(when: str):
    if not is_iso_date(when):
        abort(404)
    user_email = current_user_email()
    all_rows, all_cardio, all_weights = (
        _all_rows(user_email),
        _all_cardio(user_email),
        _all_weights(user_email),
    )
    dates = {x["date"] for x in all_rows + all_cardio + all_weights}
    prev, nxt = _neighbours(dates, when)

    prs = {
        r["id"]
        for r in stats.personal_records(all_rows, date.fromisoformat(when))
        if r["date"] == when
    }
    rows = [
        dict(r, sets_reps=_sets_summary(r["sets"], r["reps"]), pr=r["id"] in prs)
        for r in all_rows
        if r["date"] == when
    ]
    rows.reverse()  # in the order they were logged
    cardio = [c for c in reversed(all_cardio) if c["date"] == when]
    weight = next((w for w in all_weights if w["date"] == when), None)
    summary = stats.day_summary(rows, cardio)

    # Everything the share card may show. The weigh-in is deliberately not here.
    share = {
        "date": when,
        "label": f"{date.fromisoformat(when):%A %d %B %Y}".replace(" 0", " "),
        "stats": {
            "exercises": summary["entries"],
            "sets": summary["sets"],
            "reps": summary["reps"],
            "volume": summary["volume"],
            "cardio": summary["cardio"]["distance_text"],
            "minutes": summary["cardio"]["minutes_text"],
        },
        "lifts": [
            {
                "exercise": r["exercise"],
                "weight": r["weight"],
                "sets_reps": r["sets_reps"],
                "pr": r["pr"],
            }
            for r in rows
        ],
        "cardio": [
            {"activity": c["activity"], "distance": c["distance"], "duration": c["duration"]}
            for c in cardio
        ],
    }
    return render_template(
        "day.html",
        when=when,
        rows=rows,
        cardio=cardio,
        weight=weight,
        summary=summary,
        share=share,
        prev=prev,
        nxt=nxt,
        total=len(all_rows) + len(all_cardio) + len(all_weights),
        edit_url=url_for("main.search", range="all", by="day") + "#day-" + when,
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
        cardio=parsed.cardio,
        bodyweight=parsed.bodyweight,
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


def _cardio_from_form(form) -> list[dict]:
    try:
        count = min(int(form.get("num_cardio", 0)), MAX_ENTRIES)
    except ValueError:
        count = 0
    activities = []
    for i in range(count):
        if form.get(f"cardio-{i}-delete"):
            continue
        entry = normalize_cardio({f: form.get(f"cardio-{i}-{f}", "") for f in CARDIO_FORM_FIELDS})
        if entry["activity"]:
            activities.append(entry)
    return activities


def _save_bodyweight(user_email: str, when: str, weight: str) -> BodyWeight:
    """One reading per day: a second weigh-in on the same date replaces the first."""
    reading = BodyWeight.query.filter_by(user_email=user_email, date=when).first()
    if reading is None:
        reading = BodyWeight(user_email=user_email, date=when, weight=weight, notes="")
        db.session.add(reading)
    else:
        reading.weight = weight
    return reading


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
    cardio = _cardio_from_form(request.form)
    bodyweight = request.form.get("bodyweight", "").strip()
    if not (entries or cardio or bodyweight):
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
    saved_cardio = [Cardio(user_email=user_email, date=when, **c) for c in cardio]
    db.session.add_all(saved_cardio)
    reading = _save_bodyweight(user_email, when, bodyweight) if bodyweight else None
    db.session.commit()
    return render_template(
        "saved.html",
        rows=[w.as_dict() for w in saved],
        cardio=[c.as_dict() for c in saved_cardio],
        bodyweight=reading.as_dict() if reading else None,
        count=len(saved) + len(saved_cardio) + (1 if reading else 0),
        workout_date=when,
    )


# --- Search / edit ------------------------------------------------------------


@bp.route("/search", methods=["GET", "POST"])
@login_required
def search():
    user_email = current_user_email()
    if request.method == "POST":
        return _apply_search_edits(user_email)
    range_key = stats.clean_range(request.args.get("range"))
    by = stats.clean_grouping(request.args.get("by"), "7d")  # entries default to per-day
    today = _client_today()
    all_rows, all_cardio, all_weights = (
        _all_rows(user_email),
        _all_cardio(user_email),
        _all_weights(user_email),
    )
    rows = stats.filter_range(all_rows, today, range_key)
    cardio = stats.filter_range(all_cardio, today, range_key)
    weights = stats.filter_range(all_weights, today, range_key)
    return render_template(
        "search.html",
        groups=stats.group_rows(rows, by, cardio=cardio, weights=weights),
        total=len(all_rows) + len(all_cardio) + len(all_weights),
        shown=len(rows) + len(cardio) + len(weights),
        range_key=range_key,
        by=by,
    )


def _collect_edits(form, cell_re, delete_re, fields) -> tuple[dict, set]:
    edits: dict[int, dict[str, str]] = {}
    deletes: set[int] = set()
    for key, value in form.items():
        m = cell_re.match(key)
        if m and m.group(2) in fields:
            edits.setdefault(int(m.group(1)), {})[m.group(2)] = value.strip()
            continue
        m = delete_re.match(key)
        if m and value:
            deletes.add(int(m.group(1)))
    return edits, deletes


def _apply_search_edits(user_email: str):
    keep = {k: v for k, v in request.args.items() if k in ("range", "by")}
    pending = []  # (rows by id, edits, deletes, required field) per table
    for model, cell_re, delete_re, fields, required in EDITABLE:
        edits, deletes = _collect_edits(request.form, cell_re, delete_re, fields)
        ids = set(edits) | deletes
        if not ids:
            continue
        rows = model.query.filter(model.user_email == user_email, model.id.in_(ids)).all()
        pending.append(({r.id: r for r in rows}, edits, deletes, required))
    if not pending:
        return redirect(url_for("main.search", **keep))

    for by_id, edits, deletes, _required in pending:
        for rid, cells in edits.items():
            if rid in by_id and rid not in deletes and "date" in cells:
                if not is_iso_date(cells["date"]):
                    flash("Dates must be in YYYY-MM-DD format. No changes were saved.", "error")
                    return redirect(url_for("main.search", **keep))

    deleted = changed = 0
    for by_id, edits, deletes, required in pending:
        for rid, row in by_id.items():
            if rid in deletes:
                db.session.delete(row)
                deleted += 1
                continue
            cells = edits.get(rid, {})
            if required in cells and not cells[required]:
                cells.pop(required)  # never blank the name / reading itself
            dirty = False
            for field_name, value in cells.items():
                if (getattr(row, field_name) or "") != value:
                    setattr(row, field_name, value)
                    dirty = True
            changed += dirty
    db.session.commit()
    if deleted or changed:
        flash(f"Saved: {changed} updated, {deleted} deleted.", "ok")
    else:
        flash("No changes to save.", "info")
    return redirect(url_for("main.search", **keep))


# --- Progress -----------------------------------------------------------------


@bp.route("/progress")
@login_required
def progress():
    range_key, by, today = _period_args()
    user_email = current_user_email()
    all_rows = _all_rows(user_email)
    cardio = _all_cardio(user_email)
    weights = _all_weights(user_email)
    data = stats.overview(all_rows, today, range_key, by, cardio=cardio, weights=weights)
    return render_template(
        "progress.html",
        data=data,
        total=len(all_rows) + len(cardio) + len(weights),
        range_key=range_key,
        by=by,
    )


@bp.route("/exercises")
@login_required
def exercises():
    range_key = stats.clean_range(request.args.get("range"))
    user_email = current_user_email()
    today = _client_today()
    all_rows = _all_rows(user_email)
    rows = stats.filter_range(all_rows, today, range_key)
    all_cardio = _all_cardio(user_email)
    cardio = stats.cardio_summary(stats.filter_range(all_cardio, today, range_key))
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
        "exercises.html",
        summary=summary,
        cardio=cardio,
        total=len(all_rows) + len(all_cardio),
        range_key=range_key,
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
