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

from . import (
    dayedit,
    logflow,
    preferences,
    quota,
    rest,
    routines,
    session_meta,
    sessions,
    social,
    stats,
)
from .auth import current_user_email, login_required
from .exercises import (
    ACTIVITY_NAMES,
    EXERCISE_NAMES,
    TAG_SYSTEM,
    clean_tags,
    match_exercise,
)
from .extensions import db
from .llm.client import (
    BadOutputError,
    extract_json,
    test_connection,
)
from .llm.providers import PROVIDERS, LLMConfig
from .logflow import (
    MAX_ENTRIES,
    MAX_SITE_TAG_CALLS,
    LogError,
)
from .logflow import site_limit as _site_limit
from .models import BodyWeight, Cardio, Workout
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
MAX_LLM_OUTPUT = 200_000
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
    parts = home_parts(
        user_email,
        ctx["today"],
        all_data,
        request.args.get("saved", ""),
        request.args.get("session", type=int),
    )
    profile = parts.pop("profile")
    hour = _client_hour()
    return render_template(
        "home.html",
        **ctx,
        **parts,
        recorded=request.args.get("recorded") == "1",
        invite_url=(
            url_for("social.invite", code=profile.invite_code, _external=True) if profile else None
        ),
        greeting="Morning" if 4 <= hour < 12 else "Afternoon" if 12 <= hour < 17 else "Evening",
    )


def home_parts(
    user_email: str, today: str, all_data: tuple, saved: str = "", saved_n: int | None = None
) -> dict:
    """Home below the week strip: your latest workout, your recent days, friends'
    sessions and the getting-started checklist. `saved` and `saved_n` name the workout
    just logged, which then leads the page."""
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

    # The workout you just saved (the day and which one, after a log), otherwise
    # today's latest once anything is in.
    numbers = sessions.session_numbers(rows, cardio)
    dates = {x["date"] for x in rows + cardio + weights}
    latest_date = saved if saved in dates else today if today in dates else None
    latest_n = saved_n if latest_date == saved else None
    if latest_n not in numbers.get(latest_date, []):
        latest_n = numbers[latest_date][-1] if latest_date in numbers else 0
    latest = (
        _my_day_card(user_email, latest_date, latest_n, all_data, profile) if latest_date else None
    )
    just_saved = bool(latest) and latest_date == saved
    has_friends = bool(profile and social.friend_emails(user_email))
    # Getting started: three steps in place of the Friends prompts, until all are done
    # or the card is hidden.
    steps = {"logged": bool(dates), "profile": bool(profile), "friends": has_friends}
    checklist = (
        steps
        if not all(steps.values()) and not preferences.onboarding_dismissed(user_email)
        else None
    )
    return {
        "latest": latest,
        "just_saved": just_saved,
        "has_logged": bool(dates),
        "first_save": just_saved and len(dates) == 1 and len(numbers.get(latest_date, [])) <= 1,
        "checklist": checklist,
        "recent": recent,
        "friend_cards": friend_cards,
        "has_friends": has_friends,
        "profile": profile,
    }


@bp.route("/onboarding/dismiss", methods=["POST"])
@login_required
def onboarding_dismiss():
    preferences.dismiss_onboarding(current_user_email())
    return redirect(url_for("main.home"))


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
    return render_template(
        "day.html",
        **day_parts(user_email, when, request.args.get("s", type=int)),
        weight_unit=preferences.get_weight_unit(user_email),
    )


def day_parts(user_email: str, when: str, n: int | None) -> dict:
    """Everything the day page shows for your workout `n` of `when` (the day's first
    when `n` isn't one of them)."""
    all_rows, all_cardio, all_weights = (
        sessions.all_rows(user_email),
        sessions.all_cardio(user_email),
        sessions.all_weights(user_email),
    )
    dates = {x["date"] for x in all_rows + all_cardio + all_weights}
    prev, nxt = _neighbours(dates, when)
    profile = social.get_profile(user_email)
    numbers = sessions.session_numbers(all_rows, all_cardio).get(when, [0])
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
    return {
        "when": when,
        "n": n,
        "switcher": switcher,
        "title": session_meta.title_for(when, meta, n),
        "visual": session_meta.visual({"rows": rows, "cardio": cardio}, meta),
        "thread": thread,
        "rows": rows,
        "grouped_rows": _group_by_exercise(rows),
        "cardio": cardio,
        "weight": weight,
        "summary": summary,
        "share": detail["share"],
        "prev": prev,
        "nxt": nxt,
        "total": len(all_rows) + len(all_cardio) + len(all_weights),
        "edit_url": _edit_url(when, n),
    }


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

    def run():
        if config.runs_in_browser:
            return _parse_browser_output(request.form.get("llm_output", ""))
        return parse_workout(workout_text, _llm_client(config), today=today, default_unit=unit)

    try:
        parsed = logflow.parse(user_email, config, run)
    except LogError as e:
        return render_template(
            "review.html",
            error=e.message,
            limit_reached=e.code == logflow.QUOTA_EXCEEDED,
            entries=None,
            **context,
        )
    return render_template(
        "review.html",
        error=None,
        first_log=not _has_logged(user_email),
        # Nobody to share with yet: start private until there's a profile.
        visibility=None if social.get_profile(user_email) else social.PRIVATE,
        entries=parsed.entries,
        cardio=parsed.cardio,
        bodyweight=parsed.bodyweight,
        workout_date=parsed.date or today.isoformat(),
        default_title=session_meta.default_title(parsed.date or today.isoformat()),
        date_from_text=parsed.date is not None,
        **context,
    )


def _has_logged(user_email: str) -> bool:
    """Whether anything at all (a lift, cardio or a weigh-in) is saved for this user."""
    return any(
        db.session.query(model.id).filter_by(user_email=user_email).first() is not None
        for model in (Workout, Cardio, BodyWeight)
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


@bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    user_email = current_user_email()
    when = request.form.get("date", "").strip()
    config = _llm_config()
    in_browser = config is not None and config.runs_in_browser
    try:
        # Every save is its own workout: a second log on the same day is a second card.
        n = logflow.save(
            user_email,
            when,
            _client_today(),
            _entries_from_form(request.form, with_tags=in_browser),
            _cardio_from_form(request.form),
            request.form.get("bodyweight"),
            visibility=request.form.get("visibility"),
            # The name typed on the review screen; from a routine it starts out as the
            # routine's name.
            title=request.form.get("title")
            or routines.clean_title(request.form.get("routine_name")),
            get_client=(lambda: _llm_client(config)) if config else None,
            tag_calls=MAX_SITE_TAG_CALLS if config is not None and config.is_site else MAX_ENTRIES,
            in_browser=in_browser,
        )
    except LogError as e:
        flash(e.message, "error")
        return redirect(url_for("main.log"))
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
    range_key = stats.clean_range(request.args.get("range"))
    parts = sessions_parts(current_user_email(), _client_today(), range_key)
    return render_template(
        "search.html", **parts, tile_lines=SESSION_TILE_LINES, range_key=range_key
    )


def sessions_parts(user_email: str, today: date, range_key: str) -> dict:
    """Everything the Sessions list shows: your workouts in the range as cards, under
    month headings."""
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
    return {
        "months": months,
        "shown": len(days),
        "total": len(all_rows) + len(all_cardio) + len(all_weights),
    }


# --- Editing one day ------------------------------------------------------------


@bp.route("/day/<when>/edit", methods=["GET", "POST"])
@login_required
def day_edit(when: str):
    """Change, remove or add one workout's lifts and cardio, rename it, or move it to
    another date. The day's weigh-in is edited along with the day's first workout."""
    if not is_iso_date(when):
        abort(404)
    user_email = current_user_email()
    n = request.values.get("s", 0, type=int)
    if request.method == "POST":
        return _save_day_edit(user_email, when, n)
    lifts, cardio, weight = dayedit.records(user_email, when, n)
    is_first = dayedit.is_first(dayedit.other_sessions(user_email, when, n), n)
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


def _row_edits(form, prefix: str, fields, ids) -> dict:
    """The form's changes to existing rows, as dayedit.Edit wants them."""
    edits: dict = {}
    for row_id in ids:
        key = f"{prefix}-{row_id}"
        if form.get(f"{key}-delete"):
            edits[row_id] = None
        else:
            edits[row_id] = {f: form[f"{key}-{f}"].strip() for f in fields if f"{key}-{f}" in form}
    return edits


def _save_day_edit(user_email: str, when: str, n: int):
    form = request.form
    lifts, cardio, _ = dayedit.records(user_email, when, n)
    (lift_prefix, lift_fields, _), (act_prefix, act_fields, _) = DAY_EDIT_ROWS
    edit = dayedit.Edit(
        date=form.get("date", ""),
        title=form.get("title", ""),
        visibility=form.get("visibility"),
        bodyweight=form.get("bodyweight", ""),
        lifts=_row_edits(form, lift_prefix, lift_fields, [w.id for w in lifts]),
        cardio=_row_edits(form, act_prefix, act_fields, [c.id for c in cardio]),
        new_lifts=_entries_from_form(form),
        new_cardio=_cardio_from_form(form),
    )
    try:
        done = dayedit.apply(user_email, when, n, _client_today(), edit)
    except dayedit.EditError as e:
        flash(e.message, "error")
        return redirect(_edit_url(when, n))
    if done.removed and not done.weigh_in_left:
        flash("Removed that workout.", "ok")
        return redirect(url_for("main.search"))
    flash("Saved.", "ok")
    if done.removed:
        return redirect(url_for("main.day", when=done.date))
    return redirect(_day_url(done.date, done.session))


# --- Progress -----------------------------------------------------------------


@bp.route("/progress")
@login_required
def progress():
    range_key, by, today = _period_args()
    user_email = current_user_email()
    return render_template(
        "progress.html",
        **progress_parts(user_email, today, range_key, by, request.args.get("week")),
        this_year=today.year,
        range_key=range_key,
        by=by,
        rest_open=request.args.get("rest") == "1",
        weight_unit=preferences.get_weight_unit(user_email),
    )


def progress_parts(user_email: str, today: date, range_key: str, by: str, week: str | None) -> dict:
    """Everything the Progress overview shows. `week` is any date in the week the
    week card is on (this week when it is missing or still to come)."""
    this_monday = date.fromisoformat(stats.period_key(today, "week"))
    picked = stats.parse_date(week)
    monday = (
        min(date.fromisoformat(stats.period_key(picked, "week")), this_monday)
        if picked
        else this_monday
    )
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
    return {
        "data": data,
        "rest_rules": rules,
        "week_param": monday.isoformat(),
        "week_start": monday,
        "week_end": monday + timedelta(days=6),
        "prev_week": (monday - timedelta(days=7)).isoformat(),
        "next_week": (monday + timedelta(days=7)).isoformat() if monday < this_monday else None,
        "is_this_week": monday == this_monday,
        "total": len(all_rows) + len(cardio) + len(weights),
    }


def _back_to_progress(editor: bool = True):
    """Back to the week card of the Progress view the form was posted from: the same
    week, range and grouping, with the rest editor still open after a change in it."""
    week = stats.parse_date(request.form.get("week"))
    range_key, by = request.form.get("range"), request.form.get("by")
    url = url_for(
        "main.progress",
        week=week.isoformat() if week else None,
        range=range_key if range_key in stats.RANGES else None,
        by=by if by in stats.GROUPINGS else None,
        rest="1" if editor else None,
    )
    return redirect(url + "#week")


@bp.route("/rest/rules", methods=["POST"])
@login_required
def rest_rule_add():
    try:
        n = int(request.form.get("interval_days", ""))
    except ValueError:
        n = 0
    try:
        rest.add_rule(
            current_user_email(),
            request.form.get("kind", ""),
            weekdays=request.form.getlist("weekdays"),
            interval_days=n,
            anchor=stats.parse_date(request.form.get("anchor_date")) or _client_today(),
        )
    except ValueError as e:
        flash(str(e), "error")
    return _back_to_progress()


@bp.route("/rest/rules/<int:rule_id>/delete", methods=["POST"])
@login_required
def rest_rule_delete(rule_id: int):
    if not rest.delete_rule(current_user_email(), rule_id):
        abort(404)
    return _back_to_progress()


@bp.route("/rest/day/<when>", methods=["POST"])
@login_required
def rest_day_toggle(when: str):
    """Flip one day's rest on or off by hand, on top of the schedule."""
    day_date = stats.parse_date(when)
    if day_date is None:
        abort(404)
    try:
        rest.set_day(current_user_email(), day_date, _client_today())
    except ValueError:
        abort(400)
    return _back_to_progress(editor=False)


@bp.route("/exercises")
@login_required
def exercises():
    range_key = stats.clean_range(request.args.get("range"))
    parts = exercises_parts(current_user_email(), _client_today(), range_key)
    return render_template("exercises.html", **parts, range_key=range_key)


def exercises_parts(user_email: str, today: date, range_key: str) -> dict:
    """Every exercise logged in the range, the latest first, and the cardio beside it."""
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
    return {"summary": summary, "cardio": cardio, "total": len(all_rows) + len(all_cardio)}


@bp.route("/exercise/<path:name>")
@login_required
def exercise_history(name: str):
    user_email = current_user_email()
    range_key = stats.clean_range(request.args.get("range"))
    parts = exercise_parts(user_email, name, _client_today(), range_key)
    if parts is None:
        abort(404)
    return render_template(
        "exercise.html",
        **parts,
        range_key=range_key,
        weight_unit=preferences.get_weight_unit(user_email),
    )


def exercise_parts(user_email: str, name: str, today: date, range_key: str) -> dict | None:
    """One exercise's history in the range, or None if you never logged it."""
    target = name.strip().lower()
    if not target:
        return None
    workouts = (
        Workout.query.filter(
            Workout.user_email == user_email,
            func.lower(Workout.exercise) == target,
        )
        .order_by(Workout.date.asc(), Workout.id.asc())
        .all()
    )
    if not workouts:
        return None
    all_rows = [w.as_dict() for w in workouts]
    rows = stats.filter_range(all_rows, today, range_key)
    series = stats.exercise_series(rows)

    best = None
    for r in rows:
        n = stats.weight_number(r["weight"])
        if n is not None and (best is None or n > best["value"]):
            best = {"value": n, "weight": r["weight"], "date": r["date"]}
    return {
        "name": target,
        "rows": list(reversed(rows)),
        "total": len(all_rows),
        "sessions": len(series),
        "best": best,
        "volume": sum(p["volume"] for p in series),
        "last_date": rows[-1]["date"] if rows else None,
        "tags": next((r["tags"] for r in all_rows if r["tags"]), ""),
        "series": series,
        "lift": next(iter(stats.lift_progress(rows, n=1)), None),
    }
