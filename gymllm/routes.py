"""All user-facing routes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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

from . import activity, preferences, quota, routines, session_meta, sessions, social, stats
from .auth import current_user_email, login_required
from .exercises import (
    ACTIVITY_NAMES,
    EXERCISE_NAMES,
    TAG_SYSTEM,
    clean_tags,
    llm_tags,
    match_exercise,
)
from .extensions import db
from .llm.client import (
    BadOutputError,
    LLMError,
    RateLimitError,
    extract_json,
    test_connection,
)
from .llm.providers import PROVIDERS, LLMConfig
from .models import BodyWeight, Cardio, RestOverride, RestRule, Workout
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
HOME_FEED = 6  # friends' sessions on Home
HOME_RECENT = 3  # your own days in the "Your recent" list

# The day edit screen's existing lifts and cardio: (form prefix, editable fields,
# the field that may never be blanked). Fields are named "<prefix>-<id>-<field>" and
# "<prefix>-<id>-delete"; new rows use the review page's "entry-N-*" / "cardio-N-*".
DAY_EDIT_ROWS = (
    ("lift", ENTRY_FIELDS, "exercise"),
    ("act", CARDIO_FORM_FIELDS, "activity"),
)
SESSION_TILE_LINES = 3  # lines on a Sessions card before "+N more"


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
    """Prefer the browser's local date (sent by app.js) over the server's: a form
    field or ?today= first, then the `tz_offset` cookie app.js sets on every page."""
    value = request.form.get("client_date", "") or request.args.get("today", "")
    if is_iso_date(value):
        return date.fromisoformat(value)
    try:
        offset = int(request.cookies.get("tz_offset", ""))  # minutes, as JS getTimezoneOffset()
    except ValueError:
        return date.today()
    if abs(offset) > 16 * 60:
        return date.today()
    return (datetime.now(timezone.utc) - timedelta(minutes=offset)).date()


def _period_args() -> tuple[str, str, date]:
    """The `range` and `by` query params, validated, plus the reference 'today'."""
    range_key = stats.clean_range(request.args.get("range"))
    by = stats.clean_grouping(request.args.get("by"), range_key)
    return range_key, by, _client_today()


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


def _client_hour() -> int:
    """The hour of day on the user's clock, from the `tz_offset` cookie app.js sets."""
    try:
        offset = int(request.cookies.get("tz_offset", ""))
    except ValueError:
        offset = 0
    if abs(offset) > 16 * 60:
        offset = 0
    return (datetime.now(timezone.utc) - timedelta(minutes=offset)).hour


def _quota(user_email: str, config: LLMConfig) -> tuple[int | None, int | None]:
    """(free logs left today, daily limit) on the shared model, else (None, None)."""
    if not config.is_site:
        return None, None
    limit = _site_limit()
    return quota.remaining(user_email, limit), limit


def _log_context(user_email: str, config: LLMConfig) -> dict:
    """What the log box needs: the quota (shared model only), the unit toggle, and
    this week's days with the streak."""
    quota_left, quota_limit = _quota(user_email, config)
    today = _client_today()
    rows, cardio, weights = (
        sessions.all_rows(user_email),
        sessions.all_cardio(user_email),
        sessions.all_weights(user_email),
    )
    return {
        "config": config,
        "quota_left": quota_left,
        "quota_limit": quota_limit,
        "weight_unit": preferences.get_weight_unit(user_email),
        "today": today.isoformat(),
        "week": stats.week_strip(
            today,
            rows,
            cardio,
            weights,
            rest_rules=sessions.rest_rules(user_email),
            rest_overrides=sessions.rest_overrides(user_email),
        ),
        "streak": stats.week_streak({x["date"] for x in rows + cardio}, today),
        "all_data": (rows, cardio, weights),
    }


@bp.route("/")
@login_required
def home():
    """Your week and your friends' sessions; on a wide screen the log box too."""
    config = _llm_config()
    if config is None:
        flash("Choose an LLM provider before logging a workout.", "info")
        return redirect(url_for("main.settings"))
    user_email = current_user_email()
    ctx = _log_context(user_email, config)
    all_data = ctx.pop("all_data")
    rows, cardio, weights = all_data
    recent = sessions.group_sessions(rows, cardio, weights, HOME_RECENT)
    recent_metas = session_meta.for_days(user_email, {s["date"] for s in recent})
    for s in recent:
        s["summary"] = sessions.session_summary(s)
        s["title"] = session_meta.title_for(
            s["date"], recent_metas.get((s["date"], s["session"])), s["session"]
        )
    profile = social.get_profile(user_email)
    friend_cards = social.feed(user_email, limit=HOME_FEED)[0][:HOME_FEED] if profile else []

    # The workout you just saved (?saved= the day, ?session= which one, after a log),
    # otherwise today's latest once anything is in.
    numbers = sessions.session_numbers(rows, cardio)
    dates = {x["date"] for x in rows + cardio + weights}
    saved = request.args.get("saved", "")
    latest_date = saved if saved in dates else ctx["today"] if ctx["today"] in dates else None
    latest_n = request.args.get("session", type=int) if latest_date == saved else None
    if latest_n not in numbers.get(latest_date, []):
        latest_n = numbers[latest_date][-1] if latest_date in numbers else 0
    latest = (
        _my_day_card(user_email, latest_date, latest_n, all_data, profile) if latest_date else None
    )
    hour = _client_hour()
    return render_template(
        "home.html",
        **ctx,
        latest=latest,
        just_saved=bool(latest) and latest_date == saved,
        recorded=request.args.get("recorded") == "1",
        recent=recent,
        friend_cards=friend_cards,
        has_friends=bool(profile and social.friend_emails(user_email)),
        invite_url=(
            url_for("social.invite", code=profile.invite_code, _external=True) if profile else None
        ),
        greeting="Morning" if 4 <= hour < 12 else "Afternoon" if 12 <= hour < 17 else "Evening",
    )


@bp.route("/log")
@login_required
def log():
    """The log box on its own (the + tab on a phone)."""
    config = _llm_config()
    if config is None:
        flash("Choose an LLM provider before logging a workout.", "info")
        return redirect(url_for("main.settings"))
    ctx = _log_context(current_user_email(), config)
    ctx.pop("all_data")
    return render_template("log.html", **ctx)


@bp.route("/record")
@login_required
def record():
    """Record a workout as it happens: a timer and blocks of notes, all kept in the
    browser until Stop sends them to /review as one text."""
    config = _llm_config()
    if config is None:
        flash("Choose an LLM provider before logging a workout.", "info")
        return redirect(url_for("main.settings"))
    user_email = current_user_email()
    quota_left, quota_limit = _quota(user_email, config)
    # ?routine=<id> starts a workout from that routine (unless one is already live;
    # app.js decides that, since the live recording only exists in the browser).
    start = None
    if "routine" in request.args:
        routine = routines.get(user_email, request.args.get("routine", type=int) or 0)
        if routine is None:
            abort(404)
        start = {"id": routine.id, "name": routine.name, "blocks": routines.blocks_of(routine)}
    return render_template(
        "record.html",
        config=config,
        quota_left=quota_left,
        quota_limit=quota_limit,
        weight_unit=preferences.get_weight_unit(user_email),
        today=_client_today().isoformat(),
        routines=routines.list_for(user_email),
        start_routine=start,
    )


# --- Routines -------------------------------------------------------------------


def _routine_or_404(routine_id: int):
    routine = routines.get(current_user_email(), routine_id)
    if routine is None:
        abort(404)
    return routine


def _routine_editor(routine=None):
    """The editor for a new routine (routine=None) or an existing one; POST saves."""
    if request.method == "POST":
        name, error = routines.validate(request.form.get("name"))
        blocks = routines.clean_blocks(
            request.form.getlist("block_name"), request.form.getlist("block_body")
        )
        if error:
            flash(error, "error")
            return render_template(
                "routine_edit.html", routine=routine, name=name, blocks=blocks
            ), 400
        if routine is None:
            routines.create(current_user_email(), name, blocks)
        else:
            routines.update(routine, name, blocks)
        db.session.commit()
        flash(f"Saved {name}.", "ok")
        return redirect(url_for("main.routine_list"))
    return render_template(
        "routine_edit.html",
        routine=routine,
        name=routine.name if routine else "",
        blocks=routines.blocks_of(routine) if routine else [{"name": "", "body": ""}],
    )


@bp.route("/routines")
@login_required
def routine_list():
    return render_template("routines.html", routines=routines.list_for(current_user_email()))


@bp.route("/routines/new", methods=["GET", "POST"])
@login_required
def routine_new():
    return _routine_editor()


@bp.route("/routines/<int:routine_id>/edit", methods=["GET", "POST"])
@login_required
def routine_edit(routine_id: int):
    return _routine_editor(_routine_or_404(routine_id))


@bp.route("/routines/<int:routine_id>/delete", methods=["POST"])
@login_required
def routine_delete(routine_id: int):
    routine = _routine_or_404(routine_id)
    name = routine.name
    routines.delete(routine)
    db.session.commit()
    flash(f"Deleted {name}.", "ok")
    return redirect(url_for("main.routine_list"))


@bp.route("/routines/<int:routine_id>/duplicate", methods=["POST"])
@login_required
def routine_duplicate(routine_id: int):
    copy = routines.duplicate(_routine_or_404(routine_id))
    db.session.commit()
    flash(f"Made {copy.name}.", "ok")
    return redirect(url_for("main.routine_list"))


@bp.route("/log/manual")
@login_required
def log_manual():
    """Add lifts, cardio and a weigh-in by hand, with no model involved."""
    return render_template(
        "log_manual.html",
        exercise_names=[n.title() for n in EXERCISE_NAMES],
        cardio_names=ACTIVITY_NAMES,
    )


@bp.route("/weight-unit", methods=["POST"])
@login_required
def weight_unit():
    unit = preferences.set_weight_unit(current_user_email(), request.form.get("unit", ""))
    return jsonify(unit=unit)


# --- One day ------------------------------------------------------------------


def _neighbours(dates: set[str], when: str) -> tuple[str | None, str | None]:
    """The nearest logged dates before and after `when` (either may be None)."""
    before = [d for d in dates if d < when]
    after = [d for d in dates if d > when]
    return (max(before) if before else None, min(after) if after else None)


def _group_by_exercise(rows: list[dict]) -> list[dict]:
    """rows (already in log order) -> [{"exercise", "entries": [...]}], grouping every
    entry that shares an exercise name that day, in first-appearance order."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        exercise = r["exercise"]
        if exercise not in groups:
            groups[exercise] = {"exercise": exercise, "entries": []}
            order.append(exercise)
        groups[exercise]["entries"].append(
            {"weight": r["weight"], "sets_reps": r["sets_reps"], "notes": r["notes"], "pr": r["pr"]}
        )
    return [groups[k] for k in order]


def _stat_line(summary: dict) -> str:
    """The numbers under the share poster's focus name: '8 sets · 3 mi' (or exercises /
    minutes when there are no sets or distance)."""
    parts = []
    if summary["sets"]:
        parts.append(f"{summary['sets']} set{'' if summary['sets'] == 1 else 's'}")
    elif summary["entries"]:
        n = summary["exercises"]
        parts.append(f"{n} exercise{'' if n == 1 else 's'}")
    cardio = summary["cardio"]
    if cardio["lead"] or cardio["minutes_text"]:
        parts.append(cardio["lead"] or cardio["minutes_text"])
    return " · ".join(parts)


def _edit_url(when: str, n: int = 0) -> str:
    return url_for("main.day_edit", when=when, s=n or None)


def _day_url(when: str, n: int = 0) -> str:
    return url_for("main.day", when=when, s=n or None)


def _day_detail(when: str, n: int, all_rows: list[dict], all_cardio: list[dict], profile) -> dict:
    """One session's lifts in the order they were logged (with sets_reps and new-best
    flags), its cardio, its summary, and what the share poster may show."""
    prs = {
        r["id"]
        for r in stats.personal_records(all_rows, date.fromisoformat(when))
        if r["date"] == when
    }
    rows = [
        dict(r, sets_reps=sessions.sets_summary(r["sets"], r["reps"]), pr=r["id"] in prs)
        for r in all_rows
        if r["date"] == when and r["session"] == n
    ]
    rows.reverse()  # in the order they were logged
    cardio = [c for c in reversed(all_cardio) if c["date"] == when and c["session"] == n]
    summary = stats.day_summary(rows, cardio)
    d = date.fromisoformat(when)

    # Everything the share card may show. The weigh-in is deliberately not here.
    share = {
        "date": when,
        "session": n,
        "label": f"{d:%A %d %B %Y}".replace(" 0", " "),
        "short": f"{d:%a} {d.day} {d:%b}".upper(),
        "name": (profile.display_name.split()[0] if profile else "").upper(),
        "stat_line": _stat_line(summary),
        # What MuscleIcons.forTags() picks the poster's icon and focus name from.
        "hint": session_meta.icon_hint(rows, cardio),
        "stats": {
            "exercises": summary["entries"],
            "sets": summary["sets"],
            "reps": summary["reps"],
            "volume": summary["volume"],
            "cardio": summary["cardio"]["distance_text"],
            "minutes": summary["cardio"]["minutes_text"],
        },
        # One line per exercise, the same ones the session cards show.
        "lifts": sessions.exercise_lines(rows),
        "cardio": [
            {"activity": c["activity"], "distance": c["distance"], "duration": c["duration"]}
            for c in cardio
        ],
    }
    return {"rows": rows, "cardio": cardio, "summary": summary, "share": share}


def _my_day_card(user_email: str, when: str, n: int, all_data: tuple, profile) -> dict:
    """One of your workouts as a session card for Home, with the share-poster payload
    and, once you have a profile, its high fives and comments."""
    all_rows, all_cardio, all_weights = all_data
    detail = _day_detail(when, n, all_rows, all_cardio, profile)
    first = sessions.session_numbers(all_rows, all_cardio).get(when, [0])[0]
    card = {
        "date": when,
        "session": n,
        "title": session_meta.title_for(when, session_meta.get(user_email, when, n), n),
        "rows": detail["rows"],
        "cardio": detail["cardio"],
        # The day's weigh-in rides on its first workout.
        "weight": next((w for w in all_weights if w["date"] == when), None) if n == first else None,
        "share": detail["share"],
        "edit_url": _edit_url(when, n),
        "url": _day_url(when, n),
    }
    if profile and (card["rows"] or card["cardio"]):
        card["owner"] = profile
        social.attach_social([card], user_email)
    return card


@bp.route("/day/<when>")
@login_required
def day(when: str):
    """One logged workout of a day (?s= picks it, the first by default), with a
    switcher when the day has more than one."""
    if not is_iso_date(when):
        abort(404)
    user_email = current_user_email()
    all_rows, all_cardio, all_weights = (
        sessions.all_rows(user_email),
        sessions.all_cardio(user_email),
        sessions.all_weights(user_email),
    )
    dates = {x["date"] for x in all_rows + all_cardio + all_weights}
    prev, nxt = _neighbours(dates, when)
    profile = social.get_profile(user_email)
    numbers = sessions.session_numbers(all_rows, all_cardio).get(when, [0])
    n = request.args.get("s", type=int)
    if n not in numbers:
        n = numbers[0]
    detail = _day_detail(when, n, all_rows, all_cardio, profile)
    rows, cardio, summary = detail["rows"], detail["cardio"], detail["summary"]
    weight = next((w for w in all_weights if w["date"] == when), None) if n == numbers[0] else None
    thread = None
    if profile and (rows or cardio):
        thread = social.attach_social([{"owner": profile, "date": when, "session": n}], user_email)[
            0
        ]
    metas = session_meta.for_days(user_email, [when])
    meta = metas.get((when, n))
    switcher = (
        [
            {
                "n": k,
                "title": session_meta.title_for(when, metas.get((when, k)), k),
                "url": _day_url(when, k),
            }
            for k in numbers
        ]
        if len(numbers) > 1
        else []
    )
    return render_template(
        "day.html",
        when=when,
        n=n,
        switcher=switcher,
        title=session_meta.title_for(when, meta, n),
        visual=session_meta.visual({"rows": rows, "cardio": cardio}, meta),
        thread=thread,
        rows=rows,
        grouped_rows=_group_by_exercise(rows),
        cardio=cardio,
        weight=weight,
        summary=summary,
        share=detail["share"],
        prev=prev,
        nxt=nxt,
        total=len(all_rows) + len(all_cardio) + len(all_weights),
        edit_url=_edit_url(when, n),
        weight_unit=preferences.get_weight_unit(user_email),
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


def _clean_unit(value: str) -> str:
    return value if value in preferences.UNITS else preferences.DEFAULT_UNIT


@bp.route("/llm/prompt")
@login_required
def llm_prompt():
    when = request.args.get("date", "")
    if not is_iso_date(when):
        return jsonify(error="date must be YYYY-MM-DD"), 400
    unit = _clean_unit(request.args.get("unit", ""))
    return jsonify(system=build_system_prompt(date.fromisoformat(when), default_unit=unit))


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
        return redirect(url_for("main.log"))
    config = _llm_config()
    if config is None:
        flash("Set up an LLM provider first.", "error")
        return redirect(url_for("main.settings"))

    today = _client_today()
    user_email = current_user_email()
    posted_unit = request.form.get("weight_unit", "")
    if posted_unit in preferences.UNITS:
        unit = preferences.set_weight_unit(user_email, posted_unit)
    else:
        unit = preferences.get_weight_unit(user_email)
    context = {
        "workout_text": workout_text,
        "client_date": today.isoformat(),
        "config": config,
        "weight_unit": unit,
        "from_record": request.form.get("from_record") == "1",
        "routine_name": routines.clean_title(request.form.get("routine_name")),
    }
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
            parsed = parse_workout(
                workout_text, _llm_client(config), today=today, default_unit=unit
            )
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
    activity.record_parse(user_email)
    return render_template(
        "review.html",
        error=None,
        entries=parsed.entries,
        cardio=parsed.cardio,
        bodyweight=parsed.bodyweight,
        workout_date=parsed.date or today.isoformat(),
        default_title=session_meta.default_title(parsed.date or today.isoformat()),
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
        return redirect(url_for("main.log"))
    config = _llm_config()
    in_browser = config is not None and config.runs_in_browser
    entries = _entries_from_form(request.form, with_tags=in_browser)
    cardio = _cardio_from_form(request.form)
    bodyweight = request.form.get("bodyweight", "").strip()
    if not (entries or cardio or bodyweight):
        flash("Nothing to save: every row was empty or deleted.", "error")
        return redirect(url_for("main.log"))

    client = _llm_client(config) if config else None
    # Every save is its own workout: a second log on the same day is a second card.
    n = sessions.next_session(user_email, when)
    tag_calls_left = MAX_SITE_TAG_CALLS if config is not None and config.is_site else MAX_ENTRIES
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
        db.session.add(
            Workout(
                user_email=user_email,
                date=when,
                session=n,
                exercise=name,
                weight=entry["weight"],
                sets=entry["sets"],
                reps=entry["reps"],
                notes=entry["notes"],
                tags=tags,
            )
        )
    db.session.add_all(Cardio(user_email=user_email, date=when, session=n, **c) for c in cardio)
    if entries or cardio:
        # Covers the whole day, so a later save that day can change it.
        social.set_visibility(
            user_email, when, social.clean_visibility(request.form.get("visibility"))
        )
    if bodyweight:
        _save_bodyweight(user_email, when, bodyweight)  # always private
    if entries or cardio:
        # The name typed on the review screen; from a routine it starts out as the
        # routine's name.
        title = request.form.get("title") or routines.clean_title(request.form.get("routine_name"))
        session_meta.set_title(user_email, when, n, title)
    db.session.commit()
    # Straight to Home, where the workout you just saved is on top and ready to share.
    # `recorded` tells the page to clear the finished recording from the browser.
    args = {"saved": when, "session": n}
    if request.form.get("from_record") == "1":
        args["recorded"] = "1"
    return redirect(url_for("main.home", **args) + "#my-latest")


# --- Sessions -----------------------------------------------------------------


def _tile_lines(rows: list[dict], cardio: list[dict]) -> list[dict]:
    """A day's lines for its Sessions card: one per exercise and one per cardio
    activity, in the order they were logged."""
    lines = [
        {"name": ln["exercise"], "detail": ln["detail"], "parts": ln["parts"], "pr": ln["pr"]}
        for ln in sessions.exercise_lines(rows)
    ]
    for c in cardio:
        detail = " · ".join(filter(None, [c["distance"], c["duration"]]))
        lines.append({"name": c["activity"], "detail": detail, "parts": [], "pr": False})
    return lines


def _search_text(day: dict) -> str:
    """Everything the Sessions search box matches a card on, lowercased."""
    parts = [day["title"]]
    for r in day["rows"]:
        parts += [r["exercise"], r["notes"], r["tags"].replace(";", " ")]
    for c in day["cardio"]:
        parts += [c["activity"], c["notes"]]
    if day["weight"]:
        parts += ["weighed in", day["weight"]["notes"]]
    return " ".join(p for p in parts if p).lower()


@bp.route("/search")
@login_required
def search():
    """Every day you logged as a card, newest first, under month headings."""
    user_email = current_user_email()
    range_key = stats.clean_range(request.args.get("range"))
    today = _client_today()
    all_rows, all_cardio, all_weights = (
        sessions.all_rows(user_email),
        sessions.all_cardio(user_email),
        sessions.all_weights(user_email),
    )
    days = sessions.group_sessions(
        stats.filter_range(all_rows, today, range_key),
        stats.filter_range(all_cardio, today, range_key),
        stats.filter_range(all_weights, today, range_key),
    )
    prs = {r["id"] for r in stats.personal_records(all_rows, None)}
    metas = session_meta.for_days(user_email, {d["date"] for d in days})
    months: list[dict] = []
    for d in days:
        d["rows"] = [dict(r, pr=r["id"] in prs) for r in reversed(d["rows"])]  # log order
        d["cardio"] = list(reversed(d["cardio"]))
        meta = metas.get((d["date"], d["session"]))
        d["title"] = session_meta.title_for(d["date"], meta, d["session"])
        d["url"] = _day_url(d["date"], d["session"])
        d["visual"] = session_meta.visual(d, meta)
        d["lines"] = _tile_lines(d["rows"], d["cardio"])
        d["search"] = _search_text(d)
        key = d["date"][:7]
        if not months or months[-1]["key"] != key:
            label = f"{date.fromisoformat(d['date']):%B %Y}"
            months.append({"key": key, "label": label, "days": []})
        months[-1]["days"].append(d)
    return render_template(
        "search.html",
        months=months,
        shown=len(days),
        tile_lines=SESSION_TILE_LINES,
        total=len(all_rows) + len(all_cardio) + len(all_weights),
        range_key=range_key,
    )


# --- Editing one day ------------------------------------------------------------


def _day_records(user_email: str, when: str, n: int):
    """One session's lifts and cardio (in log order) and the day's weigh-in, as models."""
    lifts = (
        Workout.query.filter_by(user_email=user_email, date=when, session=n)
        .order_by(Workout.id)
        .all()
    )
    cardio = (
        Cardio.query.filter_by(user_email=user_email, date=when, session=n)
        .order_by(Cardio.id)
        .all()
    )
    weight = BodyWeight.query.filter_by(user_email=user_email, date=when).first()
    return lifts, cardio, weight


def _other_sessions(user_email: str, when: str, n: int) -> list[int]:
    """The day's other sessions' numbers."""
    rows, cardio = sessions.all_rows(user_email), sessions.all_cardio(user_email)
    return [k for k in sessions.session_numbers(rows, cardio).get(when, []) if k != n]


@bp.route("/day/<when>/edit", methods=["GET", "POST"])
@login_required
def day_edit(when: str):
    """Change, remove or add one workout's lifts and cardio, rename it, or move it to
    another date. The day's weigh-in is edited along with the day's first workout."""
    if not is_iso_date(when):
        abort(404)
    user_email = current_user_email()
    n = request.values.get("s", 0, type=int)
    lifts, cardio, weight = _day_records(user_email, when, n)
    others = _other_sessions(user_email, when, n)
    is_first = not others or n < min(others)
    if request.method == "POST":
        return _save_day_edit(user_email, when, n, lifts, cardio, weight, others, is_first)
    if not (lifts or cardio or (weight and is_first)):
        flash("Nothing is logged on that day.", "info")
        return redirect(url_for("main.day", when=when))
    meta = session_meta.get(user_email, when, n)
    lift_dicts, cardio_dicts = [w.as_dict() for w in lifts], [c.as_dict() for c in cardio]
    return render_template(
        "day_edit.html",
        when=when,
        n=n,
        lifts=lift_dicts,
        cardio=cardio_dicts,
        has_weight=is_first,
        bodyweight=weight.weight if weight and is_first else "",
        title=meta.title if meta and meta.title else "",
        default_title=session_meta.default_title(when, n),
        visual=session_meta.visual({"rows": lift_dicts, "cardio": cardio_dicts}, meta),
        visibility=social.visibilities(user_email).get(when, social.FRIENDS_ONLY),
    )


def _save_day_edit(user_email: str, when: str, n: int, lifts, cardio, weight, others, is_first):
    form = request.form
    new_date = form.get("date", "").strip() or when
    if not is_iso_date(new_date):
        flash("Pick a valid date. No changes were saved.", "error")
        return redirect(_edit_url(when, n))
    moving = new_date != when
    # The weigh-in is the day's, not a workout's: it travels with this workout only
    # when nothing else is left on the old day.
    handles_weight = is_first
    weight_moves = moving and not others
    bodyweight = form.get("bodyweight", "").strip() if handles_weight else ""
    if (
        moving
        and weight_moves
        and bodyweight
        and BodyWeight.query.filter_by(user_email=user_email, date=new_date).first() is not None
    ):
        flash(
            "You already weighed in on that day. Clear one of the two readings first. "
            "No changes were saved.",
            "error",
        )
        return redirect(_edit_url(when, n))
    new_n = sessions.next_session(user_email, new_date) if moving else n

    kept = 0
    for records, (prefix, fields, required) in zip((lifts, cardio), DAY_EDIT_ROWS, strict=True):
        for row in records:
            key = f"{prefix}-{row.id}"
            if form.get(f"{key}-delete"):
                db.session.delete(row)
                continue
            kept += 1
            for field in fields:
                if f"{key}-{field}" not in form:
                    continue
                value = form[f"{key}-{field}"].strip()
                if field == required and not value:
                    continue  # never blank the name itself
                if (getattr(row, field) or "") != value:
                    setattr(row, field, value)
                    if field == "exercise":  # a renamed lift gets its new muscle groups
                        match = match_exercise(value)
                        row.tags = match[1] if match else ""
            row.date, row.session = new_date, new_n

    for entry in _entries_from_form(form):
        match = match_exercise(entry["exercise"])
        if match:
            entry["exercise"], tags = match
        else:
            tags = ""
        db.session.add(
            Workout(user_email=user_email, date=new_date, session=new_n, tags=tags, **entry)
        )
        kept += 1
    for c in _cardio_from_form(form):
        db.session.add(Cardio(user_email=user_email, date=new_date, session=new_n, **c))
        kept += 1

    if handles_weight:
        if weight is not None and not bodyweight:
            db.session.delete(weight)
            weight = None
        elif weight is not None:
            weight.weight = bodyweight
            if weight_moves:
                weight.date = new_date
        elif bodyweight:
            weight = _save_bodyweight(
                user_email, when if not weight_moves else new_date, bodyweight
            )

    if not kept:
        session_meta.clear_session(user_email, when, n)
        if weight is None or not handles_weight:  # nothing of this workout is left
            if not others:
                session_meta.clear_day_visibility(user_email, when)
            db.session.commit()
            flash("Removed that workout.", "ok")
            return redirect(url_for("main.search"))
        db.session.commit()
        flash("Saved.", "ok")
        return redirect(url_for("main.day", when=new_date))

    if moving:
        session_meta.move_session(user_email, when, n, new_date, new_n)
        session_meta.move_reactions(user_email, when, n, new_date, new_n)
        if not others:
            session_meta.clear_day_visibility(user_email, when)
    if form.get("title", "").strip() or not moving:  # a blank title doesn't wipe the moved name
        session_meta.set_title(user_email, new_date, new_n, form.get("title", ""))
    if "visibility" in form:
        social.set_visibility(user_email, new_date, social.clean_visibility(form["visibility"]))
    db.session.commit()
    flash("Saved.", "ok")
    return redirect(_day_url(new_date, new_n))


# --- Progress -----------------------------------------------------------------


@bp.route("/progress")
@login_required
def progress():
    range_key, by, today = _period_args()
    this_monday = date.fromisoformat(stats.period_key(today, "week"))
    picked = stats.parse_date(request.args.get("week"))
    monday = (
        min(date.fromisoformat(stats.period_key(picked, "week")), this_monday)
        if picked
        else this_monday
    )
    user_email = current_user_email()
    all_rows = sessions.all_rows(user_email)
    cardio = sessions.all_cardio(user_email)
    weights = sessions.all_weights(user_email)
    rules = sessions.rest_rules(user_email)
    data = stats.overview(
        all_rows,
        today,
        range_key,
        by,
        cardio=cardio,
        weights=weights,
        week=monday,
        rest_rules=rules,
        rest_overrides=sessions.rest_overrides(user_email),
    )
    return render_template(
        "progress.html",
        data=data,
        rest_rules=rules,
        week_param=monday.isoformat(),
        week_start=monday,
        week_end=monday + timedelta(days=6),
        prev_week=(monday - timedelta(days=7)).isoformat(),
        next_week=(monday + timedelta(days=7)).isoformat() if monday < this_monday else None,
        is_this_week=monday == this_monday,
        this_year=today.year,
        total=len(all_rows) + len(cardio) + len(weights),
        range_key=range_key,
        by=by,
        weight_unit=preferences.get_weight_unit(user_email),
    )


MAX_REST_RULES = 10
REST_INTERVAL_RANGE = (2, 60)


def _back_to_progress():
    week = stats.parse_date(request.form.get("week"))
    return redirect(url_for("main.progress", week=week.isoformat() if week else None))


@bp.route("/rest/rules", methods=["POST"])
@login_required
def rest_rule_add():
    user_email = current_user_email()
    if RestRule.query.filter_by(owner_email=user_email).count() >= MAX_REST_RULES:
        flash(f"You can have up to {MAX_REST_RULES} rest rules.", "error")
        return _back_to_progress()
    if request.form.get("kind") == "interval":
        try:
            n = int(request.form.get("interval_days", ""))
        except ValueError:
            n = 0
        anchor = stats.parse_date(request.form.get("anchor_date")) or _client_today()
        if not REST_INTERVAL_RANGE[0] <= n <= REST_INTERVAL_RANGE[1]:
            flash("Pick a rest interval between 2 and 60 days.", "error")
            return _back_to_progress()
        rule = RestRule(
            owner_email=user_email, kind="interval", interval_days=n, anchor_date=anchor.isoformat()
        )
    else:
        days = sorted(set(request.form.getlist("weekdays")) & set("0123456"))
        if not days:
            flash("Pick at least one weekday.", "error")
            return _back_to_progress()
        rule = RestRule(owner_email=user_email, kind="weekdays", weekdays=",".join(days))
    db.session.add(rule)
    db.session.commit()
    return _back_to_progress()


@bp.route("/rest/rules/<int:rule_id>/delete", methods=["POST"])
@login_required
def rest_rule_delete(rule_id: int):
    rule = RestRule.query.filter_by(id=rule_id, owner_email=current_user_email()).first_or_404()
    db.session.delete(rule)
    db.session.commit()
    return _back_to_progress()


@bp.route("/rest/day/<when>", methods=["POST"])
@login_required
def rest_day_toggle(when: str):
    """Flip one day's rest on or off by hand, on top of the schedule."""
    day_date = stats.parse_date(when)
    if day_date is None:
        abort(404)
    user_email = current_user_email()
    if day_date > _client_today():
        abort(400)
    rows = sessions.all_rows(user_email) + sessions.all_cardio(user_email)
    if any(r["date"] == when for r in rows + sessions.all_weights(user_email)):
        abort(400)  # a logged day is never shown as rest
    rules = sessions.rest_rules(user_email)
    overrides = sessions.rest_overrides(user_email)
    wanted = not stats.is_rest(day_date, rules, overrides)
    row = db.session.get(RestOverride, (user_email, when))
    if wanted == stats.is_rest(day_date, rules, {}):
        if row:  # back to what the schedule says
            db.session.delete(row)
    elif row:
        row.is_rest = wanted
    else:
        db.session.add(RestOverride(owner_email=user_email, date=when, is_rest=wanted))
    db.session.commit()
    return _back_to_progress()


@bp.route("/exercises")
@login_required
def exercises():
    range_key = stats.clean_range(request.args.get("range"))
    user_email = current_user_email()
    today = _client_today()
    all_rows = sessions.all_rows(user_email)
    rows = stats.filter_range(all_rows, today, range_key)
    all_cardio = sessions.all_cardio(user_email)
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
        lift=next(iter(stats.lift_progress(rows, n=1)), None),
        range_key=range_key,
    )
