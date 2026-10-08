import json

import pytest

from gymllm import create_app, session_meta, social
from gymllm.exercises import TAG_SYSTEM
from gymllm.extensions import db
from gymllm.llm.client import AuthError
from gymllm.models import BodyWeight, Cardio, RestOverride, RestRule, Workout
from tests.conftest import OTHER, USER, base_test_config

OLLAMA_SESSION = {"provider": "ollama", "model": "llama3.2", "api_key": "", "base_url": ""}


@pytest.fixture
def local_user(client):
    """Signed in with a local provider, which the browser calls instead of the server."""
    with client.session_transaction() as s:
        s["user_email"] = USER
        s["llm"] = dict(OLLAMA_SESSION)
    return client


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"ok": True}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/"),
        ("get", "/search"),
        ("get", "/settings"),
        ("get", "/exercises"),
        ("get", "/progress"),
        ("get", "/day/2026-01-10"),
        ("get", "/record"),
        ("get", "/routines"),
        ("get", "/routines/new"),
        ("post", "/routines/new"),
        ("get", "/routines/1/edit"),
        ("post", "/routines/1/delete"),
        ("post", "/routines/1/duplicate"),
        ("post", "/review"),
        ("post", "/confirm"),
        ("get", "/day/2026-01-10/edit"),
        ("post", "/day/2026-01-10/edit"),
        ("post", "/rest/rules"),
        ("post", "/rest/rules/1/delete"),
        ("post", "/rest/day/2026-01-10"),
    ],
)
def test_anonymous_is_redirected_to_welcome(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")


def test_welcome_redirects_logged_in_user_home(logged_in):
    r = logged_in.get("/welcome")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


def test_home_without_llm_config_goes_to_settings(client):
    with client.session_transaction() as s:
        s["user_email"] = USER
    r = client.get("/", follow_redirects=True)
    assert r.request.path == "/settings"
    assert b"Choose an LLM provider" in r.data


def test_home_and_log_pages_keep_models_out_of_sight(logged_in):
    for path in ("/", "/log"):
        r = logged_in.get(path)
        assert r.status_code == 200 and b'id="log-form"' in r.data and b"Log it" in r.data
        assert b"OpenAI" not in r.data and b"gpt-4o-mini" not in r.data
    r = logged_in.get("/log")
    assert b'href="/log/manual"' in r.data and b"Writing tips" in r.data
    r = logged_in.get("/log/manual")
    assert (
        r.status_code == 200
        and b'id="classic-form"' in r.data
        and b'placeholder="160 lbs"' in r.data
    )


def test_home_lists_recent_sessions(logged_in, add_workout):
    add_workout(date="2026-01-01", exercise="older lift", tags="")
    add_workout(date="2026-02-01", exercise="newer lift", tags="")
    add_workout(date="2026-02-01", exercise="second newer lift", tags="")
    add_workout(date="2026-03-01", exercise="not mine", user_email=OTHER)
    r = logged_in.get("/")
    body = r.data.decode()
    assert r.status_code == 200
    # "Your recent": one line per day, named after the first lift logged that day.
    assert body.index("Newer lift · 2 exercises") < body.index("Older lift · 1 exercise")
    assert "not mine" not in body.lower()
    assert body.count('datetime="2026-02-01"') == 1  # one line per date


@pytest.mark.parametrize(
    "sets,reps,expected",
    [
        ("5", "5, 5, 5, 5, 5", "5, 5, 5, 5, 5"),
        ("3", "10, 8, 6", "10, 8, 6"),
        ("", "8, 8", "8, 8"),
        ("5", "12", "12, 12, 12, 12, 12"),
        ("4", "", "4"),
        ("", "", ""),
    ],
)
def test_sets_summary(sets, reps, expected):
    from gymllm.sessions import sets_summary

    assert sets_summary(sets, reps) == expected


def test_home_recent_sessions_capped(logged_in, add_workout):
    for day in range(1, 9):
        add_workout(date=f"2026-01-{day:02d}", exercise=f"lift {day}", tags="")
    body = logged_in.get("/").data.decode()
    assert "Lift 8" in body and "Lift 6" in body and "Lift 5" not in body


def test_logout_clears_auth_but_keeps_llm_settings(logged_in):
    r = logged_in.get("/logout")
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")
    with logged_in.session_transaction() as s:
        assert "user_email" not in s
        assert s["llm"]["provider"] == "openai"


# --- settings -----------------------------------------------------------------


def test_settings_post_saves_and_keeps_blank_key(logged_in):
    r = logged_in.post(
        "/settings",
        data={"provider": "openai", "model": "gpt-4o", "api_key": ""},
        follow_redirects=True,
    )
    assert b"Saved" in r.data
    with logged_in.session_transaction() as s:
        assert s["llm"]["model"] == "gpt-4o" and s["llm"]["api_key"] == "sk-test"


def test_settings_post_validation_error(logged_in):
    r = logged_in.post(
        "/settings", data={"provider": "anthropic", "model": "claude-opus-5", "api_key": ""}
    )
    assert r.status_code == 400 and b"needs an API key" in r.data


def test_settings_switching_to_ollama_needs_no_key(logged_in):
    r = logged_in.post(
        "/settings", data={"provider": "ollama", "model": "llama3.2"}, follow_redirects=True
    )
    assert b"Ollama" in r.data
    with logged_in.session_transaction() as s:
        assert s["llm"] == {
            "provider": "ollama",
            "model": "llama3.2",
            "api_key": "",
            "base_url": "",
        }


def test_settings_test_endpoint(logged_in, fake_llm):
    fake_llm.queue({"ok": True})
    r = logged_in.post(
        "/settings/test",
        data={"provider": "custom", "model": "x", "base_url": "http://models.example.com/v1"},
    )
    assert r.get_json()["ok"] is True
    r = logged_in.post(
        "/settings/test", data={"provider": "anthropic", "model": "x", "api_key": ""}
    )
    assert r.status_code == 400 and r.get_json()["ok"] is False
    # A blank key reuses the saved key for the same provider.
    fake_llm.queue({"ok": True})
    r = logged_in.post("/settings/test", data={"provider": "openai", "model": "x", "api_key": ""})
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_settings_test_refuses_local_providers(logged_in, fake_llm):
    r = logged_in.post("/settings/test", data={"provider": "ollama", "model": "llama3.2"})
    assert r.status_code == 400 and "from your browser" in r.get_json()["message"]
    assert fake_llm.calls == []


# --- browser-side LLM helpers -------------------------------------------------


def test_llm_prompt_endpoint(logged_in, client):
    r = logged_in.get("/llm/prompt?date=2026-09-14")
    assert r.status_code == 200
    assert "Monday, 2026-09-14" in r.get_json()["system"]
    assert "barbell bench press" in r.get_json()["system"]
    assert logged_in.get("/llm/prompt?date=14/09/2026").status_code == 400
    assert logged_in.get("/llm/prompt").status_code == 400


def test_llm_prompt_requires_login(client):
    r = client.get("/llm/prompt?date=2026-09-14")
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")


def test_llm_prompt_uses_default_unit(logged_in):
    kg = logged_in.get("/llm/prompt?date=2026-09-14&unit=kg").get_json()["system"]
    assert 'weight: "185 kg"' in kg
    default = logged_in.get("/llm/prompt?date=2026-09-14").get_json()["system"]  # no unit -> lbs
    assert 'weight: "185 lbs"' in default
    bogus = logged_in.get("/llm/prompt?date=2026-09-14&unit=bogus").get_json()["system"]
    assert 'weight: "185 lbs"' in bogus  # unrecognised unit falls back to lbs


def test_llm_tag_targets(logged_in):
    r = logged_in.post(
        "/llm/tag-targets",
        json={"names": ["Barbell Bench Press", "made-up movement", "", "made-up movement"]},
    )
    assert r.status_code == 200
    assert r.get_json() == {"unmatched": ["made-up movement"], "system": TAG_SYSTEM}
    assert logged_in.post("/llm/tag-targets", json={"names": "nope"}).status_code == 400
    assert logged_in.post("/llm/tag-targets", data="x").status_code == 400


# --- review / confirm ---------------------------------------------------------

PARSED = {
    "date": "2026-09-13",
    "exercises": [
        {
            "exercise": "barbell bench press",
            "weight": "185 lbs",
            "sets": 5,
            "reps": [5, 5, 5, 5, 5],
            "notes": "",
        },
        {
            "exercise": "lat pulldown",
            "weight": "120 lbs",
            "sets": 3,
            "reps": [10, 10, 10],
            "notes": "wide grip",
        },
    ],
}


def test_review_renders_editable_table(logged_in, fake_llm):
    fake_llm.queue(PARSED)
    r = logged_in.post(
        "/review", data={"workout": "bench 185 5x5 yesterday", "client_date": "2026-09-14"}
    )
    assert r.status_code == 200
    assert b'value="2026-09-13"' in r.data  # date taken from LLM
    assert b'name="entry-1-exercise"' in r.data and b"lat pulldown" in r.data
    assert b'value="5, 5, 5, 5, 5"' in r.data
    assert "2026-09-14" in fake_llm.calls[0][0]  # browser date reaches the prompt


def test_review_uses_and_persists_weight_unit(logged_in, fake_llm):
    fake_llm.queue(PARSED)
    r = logged_in.post(
        "/review",
        data={
            "workout": "bench 185 5x5 yesterday",
            "client_date": "2026-09-14",
            "weight_unit": "kg",
        },
    )
    assert r.status_code == 200
    assert 'weight: "185 kg"' in fake_llm.calls[0][0]  # the saved unit reached the prompt
    assert b'value="kg"' in r.data  # reflected back in the hidden field / toggle

    fake_llm.queue(PARSED)
    logged_in.post(
        "/review", data={"workout": "bench 185 5x5", "client_date": "2026-09-14"}
    )  # weight_unit omitted this time -> the earlier saved kg pick is still used, not reset to lbs
    assert 'weight: "185 kg"' in fake_llm.calls[1][0]


def test_review_defaults_date_to_today_when_llm_gives_none(logged_in, fake_llm):
    fake_llm.queue({"date": None, "exercises": PARSED["exercises"]})
    r = logged_in.post("/review", data={"workout": "bench", "client_date": "2026-09-14"})
    assert b'value="2026-09-14"' in r.data


def test_review_shows_friendly_llm_error(logged_in, fake_llm):
    fake_llm.error = AuthError("OpenAI rejected the API key.")
    r = logged_in.post("/review", data={"workout": "bench"})
    assert r.status_code == 200 and b"rejected the API key" in r.data
    assert b'name="entry-0-exercise"' not in r.data


def test_review_browser_mode_uses_posted_output_not_server(local_user, fake_llm):
    r = local_user.post(
        "/review",
        data={"workout": "bench", "client_date": "2026-09-14", "llm_output": json.dumps(PARSED)},
    )
    assert r.status_code == 200
    assert b'value="2026-09-13"' in r.data
    assert b'name="entry-1-exercise"' in r.data and b"lat pulldown" in r.data
    assert b"data-browser-llm" in r.data and b"localhost:11434/v1" in r.data
    assert fake_llm.calls == []  # the server never called a model


def test_review_browser_mode_tolerates_fenced_output(local_user):
    fenced = "```json\n" + json.dumps(PARSED) + "\n```"
    r = local_user.post("/review", data={"workout": "bench", "llm_output": fenced})
    assert r.status_code == 200 and b'name="entry-0-exercise"' in r.data


def test_review_browser_mode_errors(local_user):
    r = local_user.post("/review", data={"workout": "bench"})
    assert r.status_code == 200 and b"browser did not return" in r.data
    assert b'name="entry-0-exercise"' not in r.data
    r = local_user.post("/review", data={"workout": "bench", "llm_output": "not json at all"})
    assert r.status_code == 200 and b"did not return JSON" in r.data


def test_browser_output_size_cap():
    from gymllm.llm.client import BadOutputError
    from gymllm.routes import MAX_LLM_OUTPUT, _parse_browser_output

    with pytest.raises(BadOutputError, match="too large"):
        _parse_browser_output("{" * (MAX_LLM_OUTPUT + 1))


def test_log_box_runs_local_provider_in_the_browser(local_user):
    for path in ("/", "/log"):
        r = local_user.get(path)
        assert r.status_code == 200 and b"data-browser-llm" in r.data


def test_review_empty_text_redirects_to_log(logged_in):
    r = logged_in.post("/review", data={"workout": "  "})
    assert r.status_code == 302 and r.headers["Location"].endswith("/log")


def test_confirm_saves_rows_with_tags_and_skips_deleted(logged_in, app, fake_llm):
    fake_llm.queue({"tags": ["novel", "thing"]})
    data = {
        "date": "2026-09-13",
        "num_entries": "3",
        "entry-0-exercise": "Barbell Bench Press",
        "entry-0-weight": "185 lbs",
        "entry-0-sets": "5",
        "entry-0-reps": "5, 5, 5, 5, 5",
        "entry-0-notes": "",
        "entry-1-exercise": "deleted one",
        "entry-1-delete": "1",
        "entry-2-exercise": "made-up movement",
        "entry-2-weight": "10 kg",
        "entry-2-sets": "2",
        "entry-2-reps": "12, 12",
        "entry-2-notes": "",
    }
    r = logged_in.post("/confirm", data=data)
    assert (
        r.status_code == 302 and r.headers["Location"] == "/?saved=2026-09-13&session=0#my-latest"
    )
    with app.app_context():
        rows = Workout.query.order_by(Workout.id).all()
        assert [w.exercise for w in rows] == ["barbell bench press", "made-up movement"]
        assert rows[0].tags.startswith("chest") and rows[0].user_email == USER
        assert rows[1].tags == "novel;thing"
        assert rows[0].date == rows[1].date == "2026-09-13"
        assert rows[0].reps == "5, 5, 5, 5, 5" and rows[0].sets == "5"


def test_confirm_browser_mode_takes_tags_from_form(local_user, app, fake_llm):
    data = {
        "date": "2026-09-13",
        "num_entries": "2",
        "entry-0-exercise": "Barbell Bench Press",
        "entry-0-tags": "ignored, matched names keep csv tags",
        "entry-1-exercise": "made-up movement",
        "entry-1-tags": "Novel, thing; novel",
    }
    r = local_user.post("/confirm", data=data)
    assert r.status_code == 302
    assert fake_llm.calls == []
    with app.app_context():
        rows = Workout.query.order_by(Workout.id).all()
        assert rows[0].tags.startswith("chest")
        assert rows[1].tags == "novel;thing"


def test_confirm_server_mode_ignores_posted_tags(logged_in, app, fake_llm):
    fake_llm.queue({"tags": ["from-model"]})
    data = {
        "date": "2026-09-13",
        "num_entries": "1",
        "entry-0-exercise": "made-up movement",
        "entry-0-tags": "sneaky",
    }
    logged_in.post("/confirm", data=data)
    with app.app_context():
        assert Workout.query.one().tags == "from-model"


def test_confirm_rejects_bad_date_and_empty_forms(logged_in, app):
    r = logged_in.post(
        "/confirm", data={"date": "13/09/2026", "num_entries": "1", "entry-0-exercise": "x"}
    )
    assert r.status_code == 302
    r = logged_in.post(
        "/confirm", data={"date": "2026-09-13", "num_entries": "1", "entry-0-exercise": ""}
    )
    assert r.status_code == 302
    with app.app_context():
        assert Workout.query.count() == 0


# --- history ------------------------------------------------------------------


def test_exercises_index_and_history_page(logged_in, add_workout):
    add_workout(date="2026-01-01", weight="185 lbs")
    add_workout(date="2026-01-08", weight="190 lbs")
    add_workout(date="2026-01-08", weight="bodyweight", exercise="pull up")
    r = logged_in.get("/exercises")
    assert r.status_code == 200 and b"Barbell bench press" in r.data and b"Pull up" in r.data

    r = logged_in.get("/exercise/Barbell Bench Press")
    body = r.data.decode()
    assert r.status_code == 200
    assert "2 sessions" in body and "best <strong>190 lbs</strong>" in body
    assert 'class="stat-grid"' not in body  # no stat tiles, like the Overview
    assert "185 &rarr; <strong>190</strong> lbs" in body and "+5 · +3%" in body
    assert '"date": "2026-01-01"' in body and '"weight": 185.0' in body
    assert '"volume": 4625.0' in body  # 185 x 25 reps
    assert 'data-chart="line"' in body and 'data-chart="columns"' in body

    assert logged_in.get("/exercise/nothing here").status_code == 404


def test_exercises_index_shows_best_and_sparkline(logged_in, add_workout):
    add_workout(date="2026-01-01", weight="185 lbs")
    add_workout(date="2026-01-08", weight="190 lbs")
    body = logged_in.get("/exercises").data.decode()
    assert "190 lbs" in body
    assert """data-chart="spark" data-series='[185.0, 190.0]'""" in body


def test_range_filter_scopes_exercise_pages(logged_in, add_workout):
    add_workout(date="2026-01-01", weight="185 lbs")
    add_workout(date="2026-03-10", weight="190 lbs")
    body = logged_in.get("/exercises?range=30d&today=2026-03-15").data.decode()
    assert "190 lbs" in body and "185 lbs" not in body
    assert "/exercises?range=7d&amp;today=2026-03-15" in body  # filter links keep other args

    body = logged_in.get("/exercise/barbell bench press?range=7d&today=2026-03-15").data.decode()
    assert "190 lbs" in body and '"weight": 185.0' not in body

    body = logged_in.get("/exercise/barbell bench press?range=7d&today=2026-06-01").data.decode()
    assert "Nothing logged in this range" in body and "Show all time" in body


def test_progress_overview(logged_in, add_workout):
    r = logged_in.get("/progress")
    assert r.status_code == 200 and b"Nothing logged yet" in r.data

    add_workout(date="2026-03-14", exercise="barbell bench press", weight="185 lbs")
    add_workout(date="2026-03-14", exercise="pull up", weight="bodyweight", tags="back;pull")
    add_workout(date="2026-03-10", exercise="barbell bench press", weight="190 lbs")
    add_workout(date="2026-01-05", exercise="barbell bench press", weight="180 lbs")

    body = logged_in.get("/progress?range=7d&today=2026-03-15").data.decode()
    assert "Progress" in body and "Overview" in body and "Sessions" in body
    assert 'data-chart="heatmap"' not in body and "Training days" not in body
    assert 'data-chart="columns"' not in body
    # Stats under the 14th: bench and pull ups, 5 sets each.
    assert "<span>2 ex</span><span>10 sets</span>" in body
    # This week: Mon 9 – Sun 15 March, the 10th and 14th logged and linked, today ringed.
    assert body.count('class="week-day logged') == 2 and 'href="/day/2026-03-14"' in body
    assert 'class="week-day logged today"' not in body and 'class="week-day today"' in body
    assert "<strong>2</strong> of 7 days" in body
    assert "Exercise progress" in body
    assert 'aria-label="barbell bench press: top weight per session"' in body
    assert "190 &rarr; <strong>185</strong> lbs" in body  # first → latest in the range
    assert "chest" in body and "back" in body  # muscle groups
    assert "Most trained" in body
    assert "New personal bests" in body and "190" in body and "up from 180" in body
    assert "Workouts per day" in body and 'data-chart="bars"' in body
    assert "vs previous" not in body  # the stat tiles are gone

    body = logged_in.get("/progress?range=all&by=month&today=2026-03-15").data.decode()
    assert "180 &rarr; <strong>185</strong> lbs" in body  # all time starts from January

    body = logged_in.get("/progress?range=7d&today=2026-06-01").data.decode()
    assert "Nothing logged in this range" in body


def test_progress_week_arrows(logged_in, add_workout):
    add_workout(date="2026-03-03", exercise="barbell bench press", weight="185 lbs")
    body = logged_in.get("/progress?today=2026-03-15").data.decode()
    assert "Week of 9 Mar to 15 Mar" in body
    assert "week=2026-03-02" in body and 'aria-label="Next week"' not in body  # no future weeks
    assert "<strong>0</strong> of 7 days" in body

    body = logged_in.get("/progress?today=2026-03-15&week=2026-03-04").data.decode()
    assert "Week of 2 Mar to 8 Mar" in body and "<strong>1</strong> of 7 days" in body
    assert "week=2026-03-09" in body and 'class="week-jump"' in body

    body = logged_in.get("/progress?today=2026-03-15&week=2026-04-20").data.decode()
    assert "Week of 9 Mar to 15 Mar" in body  # clamped to the current week


def test_progress_today_from_tz_cookie(logged_in, add_workout, monkeypatch):
    from datetime import datetime, timezone

    from gymllm import routes

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc)  # Wed 9pm in UTC-5

    monkeypatch.setattr(routes, "datetime", FakeDateTime)
    add_workout(date="2026-09-22", exercise="barbell bench press", weight="185 lbs")
    logged_in.set_cookie("tz_offset", "300")
    body = logged_in.get("/progress").data.decode()
    assert 'title="Wed 23 Sep 2026' in body.split("week-day today")[1][:60]


def test_404_page(logged_in):
    r = logged_in.get("/does-not-exist")
    assert r.status_code == 404 and b"Page not found" in r.data


# --- csrf ---------------------------------------------------------------------


def test_csrf_enforced_when_enabled():
    cfg = base_test_config()
    cfg["WTF_CSRF_ENABLED"] = True
    app = create_app(cfg)
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = USER
    r = client.post("/confirm", data={"date": "2026-01-01"})
    assert r.status_code == 400 and b"Request rejected" in r.data
    with app.app_context():
        db.session.remove()
        db.drop_all()


# --- shared site model ---------------------------------------------------------


def test_site_model_is_default_for_new_users(site_user):
    r = site_user.get("/")
    assert r.status_code == 200
    assert b"2 free logs left today" in r.data
    assert b"Levra shared model" not in r.data


def test_site_review_uses_owner_key_and_counts_quota(site_user, site_app, fake_llm):
    from gymllm import quota

    fake_llm.queue(PARSED, PARSED)
    for _ in range(2):
        r = site_user.post("/review", data={"workout": "bench", "client_date": "2026-09-14"})
        assert r.status_code == 200 and b'name="entry-0-exercise"' in r.data
    assert len(fake_llm.calls) == 2
    assert all(c.provider == "groq" and c.api_key == "gsk-site" for c in fake_llm.configs)

    r = site_user.post("/review", data={"workout": "bench"})
    assert r.status_code == 200 and b"used today&#39;s 2 free logs" in r.data
    assert len(fake_llm.calls) == 2  # refused before any model call
    with site_app.app_context():
        assert quota.remaining(USER, 2) == 0
    r = site_user.get("/")
    assert b"0 free logs left today" in r.data and b"Come back tomorrow" in r.data


def test_site_quota_resets_next_day(site_user, site_app, fake_llm, monkeypatch):
    from gymllm import quota

    fake_llm.queue(PARSED, PARSED, PARSED)
    site_user.post("/review", data={"workout": "a"})
    site_user.post("/review", data={"workout": "b"})
    monkeypatch.setattr(quota, "today", lambda: "2099-01-01")
    r = site_user.post("/review", data={"workout": "c"})
    assert b'name="entry-0-exercise"' in r.data and len(fake_llm.calls) == 3


def test_site_rate_limit_message(site_user, fake_llm):
    from gymllm.llm.client import RateLimitError

    fake_llm.error = RateLimitError("Groq is rate-limiting you or you are out of credits.")
    r = site_user.post("/review", data={"workout": "bench"})
    assert r.status_code == 200 and b"shared model is busy" in r.data


def test_site_confirm_caps_tag_calls(site_user, app, site_app, fake_llm):
    data = {"date": "2026-09-13", "num_entries": "12"}
    for i in range(12):
        data[f"entry-{i}-exercise"] = f"made-up movement {i}"
        fake_llm.queue({"tags": [f"t{i}"]})
    r = site_user.post("/confirm", data=data)
    assert r.status_code == 302
    assert len(fake_llm.calls) == 10
    with site_app.app_context():
        tagged = [w.tags for w in Workout.query.order_by(Workout.id).all()]
        assert tagged[:10] == [f"t{i}" for i in range(10)] and tagged[10:] == ["", ""]


def test_site_option_only_offered_when_configured(site_user, logged_in):
    r = site_user.get("/settings")
    assert b'value="site" selected' in r.data and b"Levra shared model (free)" in r.data
    r = logged_in.get("/settings")
    assert b'value="site"' not in r.data
    r = logged_in.post("/settings", data={"provider": "site"})
    assert r.status_code == 400 and b"not set up on this server" in r.data


def test_site_settings_save_and_test(site_user, site_app, fake_llm):
    from gymllm import quota

    r = site_user.post("/settings", data={"provider": "site"}, follow_redirects=True)
    assert b"Saved. Using Levra shared model" in r.data
    with site_user.session_transaction() as s:
        assert s["llm"] == {"provider": "site", "model": "", "api_key": "", "base_url": ""}
    fake_llm.queue({"ok": True})
    r = site_user.post("/settings/test", data={"provider": "site"})
    assert r.get_json()["ok"] is True
    with site_app.app_context():
        assert quota.remaining(USER, 2) == 2


def test_site_user_can_still_pick_own_provider(site_user, fake_llm):
    site_user.post("/settings", data={"provider": "ollama", "model": "llama3.2"})
    r = site_user.get("/")
    assert b"data-browser-llm" in r.data and b"free logs" not in r.data


def test_quota_consume_handles_insert_race(site_app):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from gymllm import quota
    from gymllm.models import LLMUsage

    with site_app.app_context():
        assert quota.consume(USER, 2) is True
        assert quota.consume(USER, 2) is True
        assert quota.consume(USER, 2) is False
        assert quota.used(USER) == 2
        assert quota.consume(OTHER, 0) is False
        # Simulate losing an insert race: another request commits the row between
        # our existence check and our insert, so our insert fails.
        real_add = db.session.add

        def racing_add(obj):
            if isinstance(obj, LLMUsage):
                db.session.execute(
                    insert(LLMUsage).values(user_email=obj.user_email, day=obj.day, count=0)
                )
                db.session.commit()
                raise IntegrityError("dup", {}, Exception("dup"))
            real_add(obj)

        db.session.add = racing_add
        try:
            assert quota.consume("racer@example.com", 2) is True
        finally:
            db.session.add = real_add
        assert quota.used("racer@example.com") == 1


# --- cardio and body weight ---------------------------------------------------

MIXED = {
    "date": None,
    "exercises": [
        {"exercise": "pull up", "weight": "bodyweight", "sets": None, "reps": None, "notes": ""},
        {
            "exercise": "dumbbell bicep curl",
            "weight": "20 lb",
            "sets": 3,
            "reps": [10, 10, 10],
            "notes": "",
        },
    ],
    "cardio": [{"activity": "walking", "distance": "3 miles", "duration": "", "notes": ""}],
    "bodyweight": "130 lbs",
}


def test_review_shows_cardio_and_bodyweight(logged_in, fake_llm):
    fake_llm.queue(MIXED)
    r = logged_in.post(
        "/review",
        data={
            "workout": "walked 3 miles, pullups, curled 20 lb, weighed 130",
            "client_date": "2026-09-14",
        },
    )
    body = r.data.decode()
    assert r.status_code == 200
    assert 'name="cardio-0-activity" value="walking"' in body
    assert 'name="cardio-0-distance" value="3 miles"' in body
    assert 'name="bodyweight" value="130 lbs"' in body
    assert 'name="entry-1-exercise" value="dumbbell bicep curl"' in body


def test_review_with_only_a_weigh_in_is_saveable(logged_in, fake_llm):
    fake_llm.queue({"exercises": [], "cardio": [], "bodyweight": "82 kg"})
    body = logged_in.post("/review", data={"workout": "weighed in at 82 kg"}).data.decode()
    assert 'name="bodyweight" value="82 kg"' in body
    assert "No lifts in this text" in body and "No cardio in this text" in body
    assert 'class="btn btn-primary" disabled' not in body


def test_confirm_routes_each_kind_to_its_table(logged_in, app):
    data = {
        "date": "2026-09-13",
        "num_entries": "1",
        "entry-0-exercise": "pull up",
        "entry-0-weight": "bodyweight",
        "num_cardio": "2",
        "cardio-0-activity": "Walking",
        "cardio-0-distance": "3 miles",
        "cardio-0-duration": "45 min",
        "cardio-0-notes": "easy",
        "cardio-1-activity": "deleted run",
        "cardio-1-delete": "1",
        "bodyweight": "130 lbs",
    }
    r = logged_in.post("/confirm", data=data)
    assert r.status_code == 302
    with app.app_context():
        assert Workout.query.count() == 1
        c = Cardio.query.one()
        assert (c.user_email, c.date, c.activity, c.distance, c.duration, c.notes) == (
            USER,
            "2026-09-13",
            "walking",
            "3 miles",
            "45 min",
            "easy",
        )
        w = BodyWeight.query.one()
        assert (w.user_email, w.date, w.weight) == (USER, "2026-09-13", "130 lbs")

    # A second weigh-in on the same day replaces the first.
    r = logged_in.post("/confirm", data={"date": "2026-09-13", "bodyweight": "129 lbs"})
    assert r.status_code == 302
    with app.app_context():
        assert [w.weight for w in BodyWeight.query.all()] == ["129 lbs"]


def test_record_page_and_record_tab(logged_in, client):
    body = logged_in.get("/record").data.decode()
    assert 'action="/review"' in body and 'name="from_record" value="1"' in body
    assert 'textarea name="workout"' in body and "Log a past workout" in body
    assert 'class="tabbar"' not in body  # the recorder is full screen
    home = logged_in.get("/").data.decode()
    assert 'href="/record" class="tab-log' in home

    with client.session_transaction() as s:
        s.pop("llm")
    r = client.get("/record")
    assert r.status_code == 302 and r.headers["Location"].endswith("/settings")


def test_review_from_a_recording_goes_back_to_it(logged_in, fake_llm):
    fake_llm.queue(PARSED, PARSED)
    body = logged_in.post(
        "/review", data={"workout": "bench 185 5x5\n\nlat pulldown", "from_record": "1"}
    ).data.decode()
    assert body.count('name="from_record" value="1"') == 2  # try-again form and save form
    assert 'href="/record"' in body and "Back to workout" in body
    body = logged_in.post("/review", data={"workout": "bench"}).data.decode()
    assert "from_record" not in body and 'href="/log"' in body


def test_confirm_lands_on_home_with_the_day_to_share(logged_in, add_profile):
    add_profile()
    data = {
        "date": "2026-09-13",
        "from_record": "1",
        "num_entries": "1",
        "entry-0-exercise": "barbell bench press",
        "entry-0-weight": "185 lbs",
        "entry-0-sets": "3",
        "entry-0-reps": "8",
        "bodyweight": "150 lbs",
    }
    r = logged_in.post("/confirm", data=data)
    assert r.headers["Location"] == "/?saved=2026-09-13&session=0&recorded=1#my-latest"
    body = logged_in.get("/?saved=2026-09-13&recorded=1").data.decode()
    assert 'id="my-latest"' in body and "data-recording-saved" in body
    assert "latest-card is-new" in body and "Just logged" in body
    share = json.loads(body.split("data-share='", 1)[1].split("'", 1)[0])
    assert share["date"] == "2026-09-13"
    assert [lift["exercise"] for lift in share["lifts"]] == ["barbell bench press"]
    assert "150" not in json.dumps(share)  # the weigh-in never goes on the poster
    assert "High five" in body  # your profile's social bar

    # A plain visit shows today's session once there is one, without the highlight.
    body = logged_in.get("/?today=2026-09-13").data.decode()
    assert 'id="my-latest"' in body and "is-new" not in body
    assert "data-recording-saved" not in body


def test_home_without_anything_today_has_no_latest_card(logged_in, add_workout):
    add_workout(date="2026-01-10")
    body = logged_in.get("/?today=2026-09-13&saved=2026-02-02").data.decode()
    assert 'id="my-latest"' not in body


def test_confirm_with_nothing_at_all_redirects(logged_in, app):
    r = logged_in.post(
        "/confirm", data={"date": "2026-09-13", "num_cardio": "1", "cardio-0-activity": ""}
    )
    assert r.status_code == 302
    with app.app_context():
        assert Cardio.query.count() == 0


@pytest.fixture
def add_cardio(app):
    def _add(**kwargs):
        defaults = {
            "user_email": USER,
            "date": "2026-01-10",
            "activity": "walking",
            "distance": "3 miles",
            "duration": "45 min",
            "notes": "",
        }
        defaults.update(kwargs)
        with app.app_context():
            c = Cardio(**defaults)
            db.session.add(c)
            db.session.commit()
            return c.id

    return _add


@pytest.fixture
def add_weight(app):
    def _add(**kwargs):
        defaults = {"user_email": USER, "date": "2026-01-10", "weight": "130 lbs", "notes": ""}
        defaults.update(kwargs)
        with app.app_context():
            w = BodyWeight(**defaults)
            db.session.add(w)
            db.session.commit()
            return w.id

    return _add


def test_home_cards_show_cardio_and_weight(logged_in, add_workout, add_cardio, add_weight):
    add_workout(date="2026-02-01", exercise="bench", tags="")
    add_cardio(date="2026-02-01", activity="walking", distance="3 miles")
    add_cardio(date="2026-02-03", activity="swimming", distance="20 laps")  # cardio-only day
    add_weight(date="2026-02-01", weight="130 lbs")
    body = logged_in.get("/").data.decode()
    body = body[body.index("Your recent") :]
    # A cardio-only day is named after the activity; a lifting day after the lift.
    assert "Swimming · 20 laps" in body and "Bench · 1 exercise · 1 cardio" in body
    assert body.index("Swimming") < body.index("Bench")


def test_progress_and_exercises_show_cardio_and_weight(logged_in, add_cardio, add_weight):
    add_cardio(date="2026-03-12", activity="walking", distance="3 miles", duration="45 min")
    add_cardio(date="2026-03-13", activity="running", distance="2 mi", duration="20 min")
    add_weight(date="2026-03-09", weight="132 lbs")
    add_weight(date="2026-03-14", weight="130 lbs")

    body = logged_in.get("/progress?range=7d&today=2026-03-15").data.decode()
    assert "Nothing logged in this range" not in body
    assert body.count('class="week-day logged') == 4  # cardio and weigh-in days count
    assert "130 lbs" in body and "-2 lbs since" in body
    assert 'aria-label="Body weight per day"' in body
    assert '"weight": 132.0' in body and '"weight": 130.0' in body  # each on its own day
    assert "Log an exercise with a weight" in body  # no lifts in range

    body = logged_in.get("/progress?range=30d&by=week&today=2026-03-15").data.decode()
    assert 'aria-label="Body weight per week"' in body and "average of the week" in body
    assert "<th>Week</th>" in body and "Readings" in body

    # One reading still gets the chart (a single point on the period axis).
    body = logged_in.get("/progress?range=7d&today=2026-03-10").data.decode()
    assert 'aria-label="Body weight per day"' in body and "132 lbs" in body

    body = logged_in.get("/exercises?range=7d&today=2026-03-15").data.decode()
    assert "Walking" in body and "Running" in body and "3 mi" in body and "45 min" in body


# --- day page -----------------------------------------------------------------


def test_day_page_requires_iso_date(logged_in):
    assert logged_in.get("/day/13-01-2026").status_code == 404
    assert logged_in.get("/day/2026-13-01").status_code == 404


def test_day_page_shows_one_day_with_neighbours(logged_in, add_workout, add_cardio, add_weight):
    add_workout(date="2026-03-01", exercise="squat", weight="200 lbs")
    add_workout(date="2026-03-10", exercise="barbell bench press", weight="185 lbs")
    add_workout(date="2026-03-10", exercise="pull up", weight="bodyweight", sets="", reps="10, 8")
    add_cardio(date="2026-03-10", activity="walking", distance="3 miles", duration="45 min")
    add_weight(date="2026-03-10", weight="130 lbs")
    add_workout(date="2026-03-12", exercise="row")
    add_workout(date="2026-03-10", exercise="not mine", user_email=OTHER)

    r = logged_in.get("/day/2026-03-10")
    body = r.data.decode()
    assert r.status_code == 200 and "Tue 10 Mar 2026" in body
    assert "barbell bench press" in body and "pull up" in body and "walking" in body
    assert "not mine" not in body
    assert "130 lbs" in body and "never included when you share" in body
    assert 'href="/day/2026-03-01"' in body and 'href="/day/2026-03-12"' in body
    assert '<div class="stat-value">2</div>' in body  # exercises
    assert '<div class="stat-value">7</div>' in body  # 5 + 2 sets
    assert "4,625" in body  # 185 x 25
    assert "3 mi" in body and "45 min" in body
    assert 'href="/day/2026-03-10/edit"' in body
    assert "Tuesday workout" in body and 'data-icon-hint="chest' in body


def test_day_page_share_payload_excludes_body_weight(
    logged_in, add_workout, add_cardio, add_weight
):
    add_workout(date="2026-03-10", exercise="barbell bench press", weight="185 lbs")
    add_cardio(date="2026-03-10", activity="walking", distance="3 miles")
    add_weight(date="2026-03-10", weight="130 lbs")
    body = logged_in.get("/day/2026-03-10").data.decode()
    start = body.index("data-share='") + len("data-share='")
    share = json.loads(body[start : body.index("'", start)].replace("&#39;", "'"))
    assert share["date"] == "2026-03-10" and share["label"] == "Tuesday 10 March 2026"
    assert share["lifts"] == [
        {
            "exercise": "barbell bench press",
            "detail": "185 lbs · 5×5",
            "parts": [],
            "sub": "",
            "pr": False,
        }
    ]
    assert share["cardio"] == [{"activity": "walking", "distance": "3 miles", "duration": "45 min"}]
    assert share["stats"]["sets"] == 5 and share["stats"]["cardio"] == "3 mi"
    assert "130" not in json.dumps(share)
    assert share["stat_line"] == "5 sets · 3 mi" and share["short"] == "TUE 10 MAR"
    assert share["hint"].startswith("chest") and share["hint"].endswith("walking")
    assert set(share) == {
        "date",
        "session",
        "label",
        "short",
        "name",
        "stat_line",
        "hint",
        "stats",
        "lifts",
        "cardio",
    }


def test_day_page_marks_personal_records(logged_in, add_workout):
    add_workout(date="2026-03-01", weight="185 lbs")
    add_workout(date="2026-03-10", weight="190 lbs")
    add_workout(date="2026-03-10", exercise="pull up", weight="bodyweight")
    body = logged_in.get("/day/2026-03-10").data.decode()
    assert body.count('class="badge badge-best"') == 1 and "new best" in body
    assert '"pr": true' in body
    assert 'class="badge badge-best"' not in logged_in.get("/day/2026-03-01").data.decode()


def test_day_page_stacks_same_exercise_rows(logged_in, add_workout):
    add_workout(
        date="2026-03-10",
        exercise="barbell bench press",
        weight="135 lbs",
        sets="5",
        reps="5, 5, 5, 5, 5",
    )
    add_workout(
        date="2026-03-10",
        exercise="barbell bench press",
        weight="185 lbs",
        sets="3",
        reps="3, 3, 3",
    )
    add_workout(date="2026-03-10", exercise="squat", weight="225 lbs")
    body = logged_in.get("/day/2026-03-10").data.decode()
    assert body.count(">barbell bench press<") == 1  # one exercise cell, not one per weight
    assert 'rowspan="2"' in body
    assert "135 lbs" in body and "185 lbs" in body and "3×3" in body
    # The share preview: the name once, then one clause per weight on a second line.
    assert (
        '<span class="sub-part">135 lbs · 5×5,</span> <span class="sub-part">185 lbs · 3×3</span>'
        in body
    )


def test_home_card_shows_one_row_per_exercise(logged_in, add_workout):
    for weight, reps in (("30", "8, 8"), ("40", "8, 8, 8"), ("50 lbs", "5")):
        add_workout(
            date="2026-03-10", exercise="dumbbell shoulder press", weight=weight, sets="", reps=reps
        )
    add_workout(date="2026-03-10", exercise="squat", weight="225 lbs")
    add_workout(date="2026-03-03", exercise="dumbbell shoulder press", weight="20 lbs")
    body = logged_in.get("/?today=2026-03-10").data.decode()
    start = body.index('class="session-rows"')
    rows = body[start : body.index("</ul>", start)]
    assert rows.count("<li>") == 2 and rows.count("Dumbbell shoulder press") == 1
    assert "225 lbs · 5×5" in rows and rows.count('class="session-sub num"') == 1
    assert (
        '<span class="sub-part">30 lbs · 2×8,</span> <span class="sub-part">40 lbs · 3×8,</span> '
        '<span class="sub-part">50 lbs · 5</span>'
    ) in rows
    assert rows.count("badge-best") == 1  # 30, 40 and 50 all beat last week's 20: one badge


@pytest.mark.parametrize(
    "entries, parts",
    [
        (
            [("30", "8, 8"), ("50 lbs", "5"), ("40", "8")],
            ["30 lbs · 2×8", "50 lbs · 5", "40 lbs · 8"],
        ),
        ([("30", "8"), ("30 lbs", "5")], ["30 lbs · 8, 5"]),  # the same weight, merged
        ([("40 lbs", "8, 8"), ("40 lbs", "8")], ["40 lbs · 3×8"]),
        ([("bodyweight", "10"), ("bodyweight", "8")], ["bodyweight · 10, 8"]),
        ([("bodyweight", "10"), ("25 lbs", "8")], ["bodyweight · 10", "25 lbs · 8"]),
        ([("62.5 kg", "5"), ("60 kg", "")], ["62.5 kg · 5", "60 kg"]),
        ([("", ""), ("", "")], []),
    ],
)
def test_exercise_lines_put_several_weights_on_a_second_line(entries, parts):
    from gymllm.sessions import exercise_lines

    rows = [{"exercise": "press", "weight": w, "sets_reps": sr} for w, sr in entries]
    assert exercise_lines(rows) == [
        {"exercise": "press", "detail": "", "parts": parts, "sub": ", ".join(parts), "pr": False}
    ]


def test_exercise_lines_keep_a_single_weight_on_one_line():
    from gymllm.sessions import exercise_lines

    rows = [{"exercise": "bench", "weight": "185 lbs", "sets_reps": "5, 5, 5, 5, 5"}]
    assert exercise_lines(rows) == [
        {"exercise": "bench", "detail": "185 lbs · 5×5", "parts": [], "sub": "", "pr": False}
    ]


def test_exercise_lines_group_by_name_in_first_seen_order():
    from gymllm.sessions import exercise_lines

    rows = [
        {"exercise": "Squat", "weight": "225 lbs", "sets_reps": "5", "pr": False},
        {"exercise": "bench", "weight": "135 lbs", "sets_reps": "5", "pr": False},
        {"exercise": "squat", "weight": "245 lbs", "sets_reps": "3", "pr": True},
    ]
    assert exercise_lines(rows) == [
        {
            "exercise": "Squat",
            "detail": "",
            "parts": ["225 lbs · 5", "245 lbs · 3"],
            "sub": "225 lbs · 5, 245 lbs · 3",
            "pr": True,
        },
        {"exercise": "bench", "detail": "135 lbs · 5", "parts": [], "sub": "", "pr": False},
    ]


def test_day_page_empty_states(logged_in, add_workout):
    r = logged_in.get("/day/2026-03-10")
    body = r.data.decode()
    assert r.status_code == 200 and "Nothing logged on Tue 10 Mar 2026" in body
    assert "Nothing logged yet at all" in body and "share-day" not in body
    add_workout(date="2026-03-12")
    body = logged_in.get("/day/2026-03-10").data.decode()
    assert "Nothing logged on" in body and "Nothing logged yet at all" not in body
    assert 'href="/day/2026-03-12"' in body  # next logged day is still reachable
    # A cardio-only day still offers the share button; a weigh-in-only day does not.


def test_day_page_share_needs_lifts_or_cardio(logged_in, add_weight, add_cardio):
    add_weight(date="2026-03-10", weight="130 lbs")
    assert "share-day" not in logged_in.get("/day/2026-03-10").data.decode()
    add_cardio(date="2026-03-10")
    assert "share-day" in logged_in.get("/day/2026-03-10").data.decode()


def test_dates_link_to_the_day_page(logged_in, add_workout):
    add_workout(date="2026-03-10")
    assert 'href="/day/2026-03-10"' in logged_in.get("/").data.decode()
    body = logged_in.get("/search?today=2026-03-15").data.decode()
    assert 'href="/day/2026-03-10"' in body and 'id="day-2026-03-10-0"' in body
    assert 'href="/day/2026-03-10"' in logged_in.get("/exercise/barbell bench press").data.decode()
    r = logged_in.post(
        "/confirm", data={"date": "2026-03-11", "bodyweight": "130 lbs"}, follow_redirects=True
    )
    assert 'href="/day/2026-03-11"' in r.data.decode()


# --- sessions list -------------------------------------------------------------


def test_sessions_lists_day_cards_newest_first_and_only_own(logged_in, add_workout):
    add_workout(date="2026-01-01", exercise="older lift")
    add_workout(date="2026-02-03", exercise="newer lift")
    add_workout(date="2026-03-01", exercise="not mine", user_email=OTHER)
    body = logged_in.get("/search?today=2026-03-15").data.decode()
    assert body.index("Newer lift") < body.index("Older lift")
    assert "not mine" not in body.lower()
    assert 'class="session-tile" href="/day/2026-02-03"' in body
    assert "Tuesday workout" in body  # the default title: the day's weekday
    assert "February 2026" in body and "January 2026" in body  # month headings
    assert "2 sessions" in body
    assert '<input type="text"' not in body  # no spreadsheet


def test_sessions_card_lines_icon_hint_and_search_text(
    logged_in, add_workout, add_cardio, add_weight
):
    add_workout(date="2026-03-10", weight="185 lbs")
    add_workout(date="2026-03-12", weight="190 lbs", notes="felt strong")
    for name in ("squat", "deadlift", "curl"):
        add_workout(date="2026-03-12", exercise=name, tags="legs")
    add_cardio(date="2026-03-12", activity="walking", distance="3 miles")
    add_weight(date="2026-03-14", weight="130 lbs")
    body = logged_in.get("/search?today=2026-03-15").data.decode()
    assert "190 lbs · 5×5" in body and "New best" in body
    assert "+2 more" in body  # four exercises and a walk, three shown
    assert 'data-icon-hint="chest, legs, walking"' in body
    assert "felt strong" in body  # in the card's search text, not shown
    assert "Weighed in" in body and "130 lbs" in body


def test_sessions_range_filter_and_empty_states(logged_in, add_workout):
    assert b"Nothing logged yet" in logged_in.get("/search").data
    add_workout(date="2026-03-02", exercise="squat")
    add_workout(date="2026-03-12", exercise="bench")
    body = logged_in.get("/search?range=7d&today=2026-03-15").data.decode()
    assert "Bench" in body and "Squat" not in body and "1 session<" in body
    assert "Group by" not in body  # no day/week/month switch any more
    body = logged_in.get("/search?range=7d&today=2026-06-01").data.decode()
    assert "Nothing logged in this range" in body


def test_sessions_show_a_custom_title(logged_in, app, add_workout):
    add_workout(date="2026-03-10")
    with app.app_context():
        session_meta.set_title(USER, "2026-03-10", 0, "Push day")
        db.session.commit()
    body = logged_in.get("/search?today=2026-03-15").data.decode()
    assert "Push day" in body and "Tuesday workout" not in body
    assert "Push day" in logged_in.get("/day/2026-03-10").data.decode()


# --- editing one day ---------------------------------------------------------------


def test_day_edit_page_shows_pills_for_the_day(logged_in, add_workout, add_cardio, add_weight):
    a = add_workout(date="2026-03-10")
    c = add_cardio(date="2026-03-10", activity="walking", distance="3 miles")
    add_weight(date="2026-03-10", weight="130 lbs")
    add_workout(date="2026-03-11", exercise="other day")
    body = logged_in.get("/day/2026-03-10/edit").data.decode()
    assert f'name="lift-{a}-weight" value="185 lbs"' in body
    assert f'name="act-{c}-distance" value="3 miles"' in body
    assert 'name="bodyweight" value="130 lbs"' in body
    assert 'placeholder="Tuesday workout"' in body
    assert 'name="date" value="2026-03-10"' in body
    assert "other day" not in body
    assert 'id="entry-template"' in body and 'id="cardio-template"' in body


def test_day_edit_on_an_empty_day_goes_back_to_the_day(logged_in):
    r = logged_in.get("/day/2026-03-10/edit")
    assert r.status_code == 302 and r.headers["Location"].endswith("/day/2026-03-10")
    assert logged_in.get("/day/nope/edit").status_code == 404


def test_day_edit_saves_changes_removals_and_new_rows(logged_in, app, add_workout, add_cardio):
    a = add_workout(date="2026-03-10")
    b = add_workout(date="2026-03-10", exercise="curl")
    c = add_cardio(date="2026-03-10", activity="walking", distance="3 miles")
    r = logged_in.post(
        "/day/2026-03-10/edit",
        data={
            "date": "2026-03-10",
            "title": "Chest day",
            f"lift-{a}-weight": "200 lbs",
            f"lift-{a}-exercise": "",  # blank name is ignored
            f"lift-{b}-delete": "1",
            f"act-{c}-distance": "4 miles",
            "num_entries": "1",
            "entry-0-exercise": "squat",
            "entry-0-weight": "225 lbs",
            "entry-0-sets": "3",
            "entry-0-reps": "5",
            "num_cardio": "1",
            "cardio-0-activity": "rowing",
            "cardio-0-duration": "10 min",
            "bodyweight": "131 lbs",
            "visibility": "private",
        },
    )
    assert r.status_code == 302 and r.headers["Location"].endswith("/day/2026-03-10")
    with app.app_context():
        assert Workout.query.get(a).weight == "200 lbs"
        assert Workout.query.get(a).exercise == "barbell bench press"
        assert Workout.query.get(b) is None
        assert Cardio.query.get(c).distance == "4 miles"
        new = Workout.query.filter_by(date="2026-03-10").filter(Workout.id != a).one()
        assert new.weight == "225 lbs" and new.tags  # matched and tagged
        assert Cardio.query.filter_by(activity="rowing").one().duration == "10 min"
        assert BodyWeight.query.filter_by(user_email=USER).one().weight == "131 lbs"
        assert session_meta.get(USER, "2026-03-10").title == "Chest day"
        assert social.visibilities(USER) == {"2026-03-10": "private"}


def test_day_edit_title_back_to_default_clears_it(logged_in, app, add_workout):
    add_workout(date="2026-03-10")
    with app.app_context():
        session_meta.set_title(USER, "2026-03-10", 0, "Push day")
        db.session.commit()
    logged_in.post("/day/2026-03-10/edit", data={"date": "2026-03-10", "title": " "})
    with app.app_context():
        assert session_meta.get(USER, "2026-03-10") is None
    logged_in.post("/day/2026-03-10/edit", data={"date": "2026-03-10", "title": "Tuesday workout"})
    with app.app_context():
        assert session_meta.get(USER, "2026-03-10") is None


def test_day_edit_moves_the_whole_day(logged_in, app, add_workout, add_cardio, add_weight):
    a = add_workout(date="2026-03-10")
    c = add_cardio(date="2026-03-10")
    w = add_weight(date="2026-03-10", weight="130 lbs")
    stay = add_workout(date="2026-03-11", exercise="stays put")
    r = logged_in.post(
        "/day/2026-03-10/edit",
        data={
            "date": "2026-03-14",
            "title": "Moved",
            "bodyweight": "130 lbs",
            "visibility": "public",
        },
    )
    assert r.headers["Location"].endswith("/day/2026-03-14")
    with app.app_context():
        assert Workout.query.get(a).date == "2026-03-14"
        assert Cardio.query.get(c).date == "2026-03-14"
        assert BodyWeight.query.get(w).date == "2026-03-14"
        assert Workout.query.get(stay).date == "2026-03-11"
        assert session_meta.get(USER, "2026-03-10") is None
        assert session_meta.get(USER, "2026-03-14").title == "Moved"
        assert social.visibilities(USER) == {"2026-03-14": "friends"}  # Public is gone


def test_day_edit_refuses_a_second_weigh_in_on_the_new_date(
    logged_in, app, add_workout, add_weight
):
    a = add_workout(date="2026-03-10")
    add_weight(date="2026-03-10", weight="130 lbs")
    add_weight(date="2026-03-14", weight="128 lbs")
    r = logged_in.post(
        "/day/2026-03-10/edit",
        data={"date": "2026-03-14", "bodyweight": "130 lbs"},
        follow_redirects=True,
    )
    assert b"already weighed in" in r.data
    with app.app_context():
        assert Workout.query.get(a).date == "2026-03-10"


def test_day_edit_rejects_a_bad_date_and_other_users_rows(logged_in, app, add_workout):
    a = add_workout(date="2026-03-10")
    theirs = add_workout(date="2026-03-10", user_email=OTHER)
    r = logged_in.post(
        "/day/2026-03-10/edit",
        data={"date": "soon", f"lift-{a}-weight": "1 lbs"},
        follow_redirects=True,
    )
    assert b"valid date" in r.data
    logged_in.post(
        "/day/2026-03-10/edit",
        data={"date": "2026-03-10", f"lift-{theirs}-delete": "1", f"lift-{theirs}-weight": "0"},
    )
    with app.app_context():
        assert Workout.query.get(a).weight == "185 lbs"
        assert Workout.query.get(theirs).weight == "185 lbs"


def test_day_edit_removing_everything_clears_the_day(logged_in, app, add_workout):
    a = add_workout(date="2026-03-10")
    with app.app_context():
        session_meta.set_title(USER, "2026-03-10", 0, "Gone")
        db.session.commit()
    r = logged_in.post("/day/2026-03-10/edit", data={"date": "2026-03-10", f"lift-{a}-delete": "1"})
    assert r.headers["Location"].endswith("/search")
    with app.app_context():
        assert Workout.query.get(a) is None and session_meta.get(USER, "2026-03-10") is None


# --- routines -------------------------------------------------------------------


def _new_routine(client, name="Push day", blocks=(("Chest", "Bench 185 lbs, 3 sets of ___"),)):
    data = {
        "name": name,
        "block_name": [b[0] for b in blocks],
        "block_body": [b[1] for b in blocks],
    }
    return client.post("/routines/new", data=data)


def _routine_ids(app, email=USER):
    from gymllm import routines

    with app.app_context():
        return [r["id"] for r in routines.list_for(email)]


def test_routine_crud(logged_in, app):
    from gymllm import routines

    body = logged_in.get("/routines").data.decode()
    assert "No routines yet." in body and 'href="/routines/new"' in body
    assert 'name="block_body"' in logged_in.get("/routines/new").data.decode()

    r = _new_routine(
        logged_in, blocks=[("Warm-up", "Row 5 min"), ("", "Dips 3 sets of ___"), ("Chest", "Bench")]
    )
    assert r.status_code == 302 and r.headers["Location"].endswith("/routines")
    [rid] = _routine_ids(app)
    body = logged_in.get("/routines").data.decode()
    assert "Push day" in body and "3 blocks" in body
    with app.app_context():
        assert [b["name"] for b in routines.blocks_of(routines.get(USER, rid))] == [
            "Warm-up",
            "",
            "Chest",
        ]

    edit = logged_in.get(f"/routines/{rid}/edit").data.decode()
    assert 'value="Push day"' in edit and "Dips 3 sets of ___" in edit
    r = logged_in.post(
        f"/routines/{rid}/edit",
        data={
            "name": "Push A",
            "block_name": ["Chest", "Warm-up"],
            "block_body": ["Bench", "Row 5 min"],
        },
    )
    assert r.status_code == 302
    with app.app_context():
        routine = routines.get(USER, rid)
        assert routine.name == "Push A"
        assert routines.blocks_of(routine) == [
            {"name": "Chest", "body": "Bench"},
            {"name": "Warm-up", "body": "Row 5 min"},
        ]

    assert logged_in.post(f"/routines/{rid}/duplicate").status_code == 302
    ids = _routine_ids(app)
    assert len(ids) == 2
    assert "Push A (copy)" in logged_in.get("/routines").data.decode()

    assert logged_in.post(f"/routines/{rid}/delete").status_code == 302
    assert _routine_ids(app) == [i for i in ids if i != rid]


def test_routine_name_is_required(logged_in, app):
    r = _new_routine(logged_in, name="   ")
    assert r.status_code == 400 and b"Give the routine a name." in r.data
    assert b"Bench 185 lbs, 3 sets of ___" in r.data  # what you wrote is still there
    assert _routine_ids(app) == []


def test_another_users_routine_is_not_found(logged_in, other_client, app):
    _new_routine(other_client, name="Theirs")
    [rid] = _routine_ids(app, OTHER)
    assert logged_in.get(f"/routines/{rid}/edit").status_code == 404
    assert logged_in.post(f"/routines/{rid}/edit", data={"name": "Mine now"}).status_code == 404
    assert logged_in.post(f"/routines/{rid}/delete").status_code == 404
    assert logged_in.post(f"/routines/{rid}/duplicate").status_code == 404
    assert logged_in.get(f"/record?routine={rid}").status_code == 404
    assert "Theirs" not in logged_in.get("/routines").data.decode()
    assert "Theirs" not in logged_in.get("/record").data.decode()
    assert _routine_ids(app, OTHER) == [rid] and _routine_ids(app) == []


def test_routine_posts_need_csrf():
    cfg = base_test_config()
    cfg["WTF_CSRF_ENABLED"] = True
    app = create_app(cfg)
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = USER
    r = client.post("/routines/new", data={"name": "Push"})
    assert r.status_code == 400
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_record_lists_routines_and_starts_one(logged_in, app):
    body = logged_in.get("/record").data.decode()
    assert "No routines yet." in body and 'href="/routines"' in body
    assert "data-rec-routine=" not in body

    _new_routine(logged_in, blocks=[("Chest", "Bench 185 lbs, 3 sets of ___"), ("", "Dips")])
    [rid] = _routine_ids(app)
    body = logged_in.get("/record").data.decode()
    assert f'href="/record?routine={rid}"' in body and "Push day" in body and "2 blocks" in body

    body = logged_in.get(f"/record?routine={rid}").data.decode()
    start = json.loads(body.split("data-rec-routine='", 1)[1].split("'", 1)[0])
    assert start == {
        "id": rid,
        "name": "Push day",
        "blocks": [
            {"name": "Chest", "body": "Bench 185 lbs, 3 sets of ___"},
            {"name": "", "body": "Dips"},
        ],
    }
    assert 'name="routine_name"' in body
    assert logged_in.get("/record?routine=999").status_code == 404
    assert logged_in.get("/record?routine=abc").status_code == 404


def test_review_carries_the_routine_name(logged_in, fake_llm):
    fake_llm.queue(PARSED)
    body = logged_in.post(
        "/review",
        data={"workout": "Chest\nbench 185 5x5", "from_record": "1", "routine_name": "Push day"},
    ).data.decode()
    assert body.count('name="routine_name" value="Push day"') == 2  # try-again form and save form
    fake_llm.queue(PARSED)
    body = logged_in.post("/review", data={"workout": "bench 185 5x5"}).data.decode()
    assert "routine_name" not in body


def test_confirm_with_routine_name_titles_the_day(logged_in, app):
    lift = {
        "num_entries": "1",
        "entry-0-exercise": "barbell bench press",
        "entry-0-weight": "185 lbs",
    }
    logged_in.post("/confirm", data={"date": "2026-09-13", "routine_name": " Push  day ", **lift})
    logged_in.post("/confirm", data={"date": "2026-09-14", **lift})
    logged_in.post("/confirm", data={"date": "2026-09-15", "routine_name": "", **lift})
    with app.app_context():
        assert session_meta.get(USER, "2026-09-13").title == "Push day"
        assert session_meta.get(USER, "2026-09-14") is None
        assert session_meta.get(USER, "2026-09-15") is None


# --- Rest days -----------------------------------------------------------------


def _count(app, model):
    with app.app_context():
        return model.query.count()


def _one(app, model):
    with app.app_context():
        return model.query.one()


def _rest_tiles(body):
    return body.count('class="week-day rest')


def test_weekly_rest_rule_shows_on_progress_strip(logged_in, add_workout):
    add_workout(date="2026-03-10")  # a Tuesday: logged, so never shown as rest
    r = logged_in.post("/rest/rules", data={"kind": "weekdays", "weekdays": ["1", "6"]})
    assert r.status_code == 302
    body = logged_in.get("/progress?today=2026-03-12").data.decode()
    assert _rest_tiles(body) == 1  # Sunday only; Tuesday is logged
    assert "<strong>1</strong> of 7 days" in body  # counts unchanged


def test_interval_rule_and_validation(app, logged_in, add_workout):
    add_workout(date="2026-03-01")  # the week card only shows once something is logged
    logged_in.post(
        "/rest/rules", data={"kind": "interval", "interval_days": "3", "anchor_date": "2026-03-09"}
    )
    assert _count(app, RestRule) == 1
    logged_in.post("/rest/rules", data={"kind": "interval", "interval_days": "1"})
    logged_in.post("/rest/rules", data={"kind": "weekdays"})
    logged_in.post("/rest/rules", data={"kind": "weekdays", "weekdays": ["9"]})
    assert _count(app, RestRule) == 1
    body = logged_in.get("/progress?today=2026-03-12").data.decode()
    assert _rest_tiles(body) == 3  # Mar 9, 12, 15


def test_rest_rule_delete_is_owner_only(app, logged_in, other_client):
    logged_in.post("/rest/rules", data={"kind": "weekdays", "weekdays": ["0"]})
    rule_id = _one(app, RestRule).id
    assert other_client.post(f"/rest/rules/{rule_id}/delete").status_code == 404
    assert logged_in.post(f"/rest/rules/{rule_id}/delete").status_code == 302
    assert _count(app, RestRule) == 0


def test_rest_day_toggle_overrides_schedule(app, logged_in):
    path = "/rest/day/2026-03-10?today=2026-03-12"
    assert logged_in.post(path).status_code == 302  # one-off rest
    assert _one(app, RestOverride).is_rest is True
    logged_in.post(path)  # back to normal: row removed
    assert _count(app, RestOverride) == 0
    logged_in.post("/rest/rules", data={"kind": "weekdays", "weekdays": ["1"]})
    logged_in.post(path)  # cancel a scheduled rest
    assert _one(app, RestOverride).is_rest is False
    body = logged_in.get("/progress?today=2026-03-12&week=2026-03-09").data.decode()
    # the page needs something logged to show the week card
    assert _rest_tiles(body) == 0


def test_rest_day_toggle_refuses_future_logged_and_bad_dates(app, logged_in, add_workout):
    add_workout(date="2026-03-10")
    assert logged_in.post("/rest/day/2026-03-10?today=2026-03-12").status_code == 400
    assert logged_in.post("/rest/day/2026-03-20?today=2026-03-12").status_code == 400
    assert logged_in.post("/rest/day/nope").status_code == 404
    assert _count(app, RestOverride) == 0


# --- QA pass: validation, future dates, where rest actions land -------------------


def _lift(weight="185 lbs", **extra):
    return {
        "date": "2026-03-10",
        "client_date": "2026-03-12",
        "num_entries": "1",
        "entry-0-exercise": "bench press",
        "entry-0-weight": weight,
        "entry-0-sets": "3",
        "entry-0-reps": "5",
        **extra,
    }


def test_confirm_refuses_a_future_date(app, logged_in):
    r = logged_in.post("/confirm", data=_lift(date="2026-03-13"))
    assert r.status_code == 302 and r.headers["Location"].endswith("/log")
    assert logged_in.post("/confirm", data=_lift(date="2026-03-12")).status_code == 302  # today
    with app.app_context():
        assert [w.date for w in Workout.query.all()] == ["2026-03-12"]


@pytest.mark.parametrize(
    "data", [_lift(weight="my weird lift"), _lift(bodyweight="abc"), _lift(bodyweight="12 stone")]
)
def test_confirm_refuses_weights_that_are_not_weights(app, logged_in, data):
    r = logged_in.post("/confirm", data=data, follow_redirects=True)
    assert "Nothing was saved" in r.data.decode()
    with app.app_context():
        assert Workout.query.count() == 0 and BodyWeight.query.count() == 0


def test_confirm_adds_the_unit_to_bare_values(app, logged_in):
    data = _lift(weight="50", bodyweight="160")
    data.update({"num_cardio": "1", "cardio-0-activity": "rowing", "cardio-0-duration": "30"})
    data.update({"num_entries": "2", "entry-1-exercise": "pull up", "entry-1-weight": "BW"})
    logged_in.post("/confirm", data=data)
    with app.app_context():
        assert [w.weight for w in Workout.query.order_by(Workout.id)] == ["50 lbs", "BW"]
        assert Cardio.query.one().duration == "30 min"
        assert BodyWeight.query.one().weight == "160 lbs"


def test_day_edit_refuses_a_future_date_and_bad_weights(app, logged_in, add_workout):
    w = add_workout(date="2026-03-10")
    path = "/day/2026-03-10/edit"
    form = {"client_date": "2026-03-12", "date": "2026-03-10", f"lift-{w}-exercise": "squat"}
    r = logged_in.post(path, data={**form, "date": "2026-03-20"})
    assert r.headers["Location"].endswith(path)
    r = logged_in.post(path, data={**form, f"lift-{w}-weight": "heavy"})
    assert r.headers["Location"].endswith(path)
    with app.app_context():
        row = db.session.get(Workout, w)
        assert (row.date, row.exercise, row.weight) == (
            "2026-03-10",
            "barbell bench press",
            "185 lbs",
        )
    logged_in.post(path, data={**form, f"lift-{w}-weight": "50"})
    with app.app_context():
        row = db.session.get(Workout, w)
        assert (row.exercise, row.weight) == ("squat", "50 lbs")


def test_rest_actions_come_back_to_the_same_progress_view(app, logged_in):
    place = {"week": "2026-03-09", "range": "30d", "by": "week"}
    r = logged_in.post("/rest/rules", data={"kind": "weekdays", "weekdays": ["0"], **place})
    assert r.headers["Location"] == "/progress?week=2026-03-09&range=30d&by=week&rest=1#week"
    r = logged_in.post("/rest/day/2026-03-10?today=2026-03-12", data={**place, "range": "nope"})
    assert r.headers["Location"] == "/progress?week=2026-03-09&by=week#week"
