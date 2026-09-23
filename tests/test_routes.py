import json

import pytest

from gymllm import create_app
from gymllm.exercises import TAG_SYSTEM
from gymllm.extensions import db
from gymllm.llm.client import AuthError
from gymllm.models import BodyWeight, Cardio, Workout
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
        ("post", "/review"),
        ("post", "/confirm"),
        ("post", "/search"),
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


def test_home_shows_provider_in_use(logged_in):
    r = logged_in.get("/")
    assert r.status_code == 200 and b"OpenAI" in r.data and b"gpt-4o-mini" in r.data


def test_home_lists_recent_sessions(logged_in, add_workout):
    add_workout(date="2026-01-01", exercise="older lift")
    add_workout(date="2026-02-01", exercise="newer lift")
    add_workout(date="2026-02-01", exercise="second newer lift")
    add_workout(date="2026-03-01", exercise="not mine", user_email=OTHER)
    r = logged_in.get("/")
    body = r.data.decode()
    assert r.status_code == 200
    assert body.index("newer lift") < body.index("older lift")
    assert "second newer lift" in body and "not mine" not in body
    assert body.count('datetime="2026-02-01"') == 1  # one session heading per date


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
    from gymllm.routes import _sets_summary

    assert _sets_summary(sets, reps) == expected


def test_home_recent_sessions_capped(logged_in, add_workout):
    for day in range(1, 9):
        add_workout(date=f"2026-01-{day:02d}", exercise=f"lift {day}")
    body = logged_in.get("/").data.decode()
    assert "lift 8" in body and "lift 4" in body and "lift 3" not in body


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
    r2 = logged_in.post(
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


def test_home_shows_browser_hint_for_local_provider(local_user):
    r = local_user.get("/")
    assert r.status_code == 200 and b"in your browser" in r.data and b"data-browser-llm" in r.data


def test_review_empty_text_redirects_home(logged_in):
    r = logged_in.post("/review", data={"workout": "  "})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


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
    assert r.status_code == 200 and b"Logged 2 entries" in r.data
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
    assert r.status_code == 200 and b"Logged 2 entries" in r.data
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


# --- search / edit ------------------------------------------------------------


def test_search_lists_newest_first_and_only_own_rows(logged_in, add_workout):
    add_workout(date="2026-01-01", exercise="older")
    add_workout(date="2026-02-01", exercise="newer")
    add_workout(date="2026-03-01", exercise="not mine", user_email=OTHER)
    r = logged_in.get("/search")
    body = r.data.decode()
    assert body.index('value="newer"') < body.index('value="older"')
    assert "not mine" not in body


def test_search_edit_and_delete_by_id(logged_in, app, add_workout):
    a = add_workout(exercise="a")
    b = add_workout(exercise="b")
    c = add_workout(exercise="c")
    r = logged_in.post(
        "/search",
        data={
            f"cell-{a}-weight": "200 lbs",
            f"cell-{a}-date": "2026-01-10",
            f"delete-{b}": "1",
            f"cell-{c}-exercise": "",
        },
        follow_redirects=True,
    )
    assert b"1 updated, 1 deleted" in r.data
    with app.app_context():
        assert Workout.query.get(a).weight == "200 lbs"
        assert Workout.query.get(b) is None
        assert Workout.query.get(c).exercise == "c"  # blank name ignored


def test_search_cannot_touch_other_users_rows(logged_in, app, add_workout):
    theirs = add_workout(exercise="theirs", user_email=OTHER)
    logged_in.post(
        "/search",
        data={f"delete-{theirs}": "1", f"cell-{theirs}-weight": "0"},
        follow_redirects=True,
    )
    with app.app_context():
        w = Workout.query.get(theirs)
        assert w is not None and w.weight == "185 lbs"


def test_search_rejects_invalid_date_without_saving(logged_in, app, add_workout):
    a = add_workout()
    r = logged_in.post(
        "/search", data={f"cell-{a}-date": "Jan 5", f"cell-{a}-weight": "1"}, follow_redirects=True
    )
    assert b"YYYY-MM-DD" in r.data
    with app.app_context():
        assert Workout.query.get(a).weight == "185 lbs"


def test_search_ignores_nonexistent_ids(logged_in):
    r = logged_in.post(
        "/search", data={"cell-99999-weight": "1", "delete-4242": "1"}, follow_redirects=True
    )
    assert r.status_code == 200


# --- history ------------------------------------------------------------------


def test_exercises_index_and_history_page(logged_in, add_workout):
    add_workout(date="2026-01-01", weight="185 lbs")
    add_workout(date="2026-01-08", weight="190 lbs")
    add_workout(date="2026-01-08", weight="bodyweight", exercise="pull up")
    r = logged_in.get("/exercises")
    assert r.status_code == 200 and b"barbell bench press" in r.data and b"pull up" in r.data

    r = logged_in.get("/exercise/Barbell Bench Press")
    body = r.data.decode()
    assert r.status_code == 200
    assert "190 lbs" in body and '<div class="stat-value">2</div>' in body
    assert '"date": "2026-01-01"' in body and '"weight": 185.0' in body
    assert '"volume": 4625.0' in body  # 185 x 25 reps
    assert 'data-chart="line"' in body and 'data-chart="columns"' in body

    r = logged_in.get("/exercise/nothing here")
    assert r.status_code == 200 and b"No entries" in r.data


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


def test_sessions_page_groups_by_period(logged_in, add_workout):
    add_workout(date="2026-03-02", exercise="squat")
    add_workout(date="2026-03-10", exercise="bench")
    add_workout(date="2026-03-12", exercise="row")
    add_workout(date="2026-03-12", exercise="not mine", user_email=OTHER)

    body = logged_in.get("/search?today=2026-03-15").data.decode()  # default: all time, by day
    assert "Thu 12 Mar 2026" in body and "Tue 10 Mar 2026" in body and "Mon 2 Mar 2026" in body
    assert body.index("Thu 12 Mar 2026") < body.index("Mon 2 Mar 2026")
    assert "not mine" not in body and "3 rows" in body

    body = logged_in.get("/search?range=7d&by=week&today=2026-03-15").data.decode()
    assert "9–15 Mar 2026" in body and "2 sessions" in body
    assert "squat" not in body and "bench" in body and "row" in body

    body = logged_in.get("/search?range=all&by=month&today=2026-03-15").data.decode()
    assert "March 2026" in body and "3 sessions" in body

    body = logged_in.get("/search?range=7d&today=2026-06-01").data.decode()
    assert "Nothing logged in this range" in body


def test_search_edits_redirect_back_to_same_view(logged_in, app, add_workout):
    a = add_workout(exercise="a")
    r = logged_in.post("/search?range=30d&by=week", data={f"cell-{a}-weight": "200 lbs"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/search?range=30d&by=week")


def test_progress_overview(logged_in, add_workout):
    r = logged_in.get("/progress")
    assert r.status_code == 200 and b"Nothing logged yet" in r.data

    add_workout(date="2026-03-14", exercise="barbell bench press", weight="185 lbs")
    add_workout(date="2026-03-14", exercise="pull up", weight="bodyweight", tags="back;pull")
    add_workout(date="2026-03-10", exercise="barbell bench press", weight="190 lbs")
    add_workout(date="2026-01-05", exercise="barbell bench press", weight="180 lbs")

    body = logged_in.get("/progress?range=7d&today=2026-03-15").data.decode()
    assert "Progress" in body and "Overview" in body and "Sessions" in body
    assert 'data-chart="columns"' in body and 'data-chart="heatmap"' in body
    assert '"key": "2026-03-09"' in body and '"key": "2026-03-15"' in body  # zero-filled week
    assert "chest" in body and "back" in body  # muscle groups
    assert "Personal records" in body and "190 lbs" in body and "up from 180" in body
    assert "+2 vs previous 7d" in body  # sessions delta: 2 this week, none the week before
    assert '"count": 2' in body  # heatmap cell for the 14th

    body = logged_in.get("/progress?range=all&by=month&today=2026-03-15").data.decode()
    assert "per month" in body and '"label": "Jan 2026"' in body and '"label": "Feb 2026"' in body
    assert "vs previous" not in body  # no deltas for all time

    body = logged_in.get("/progress?range=7d&today=2026-06-01").data.decode()
    assert "Nothing logged in this range" in body


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
    assert b"2 of 2 free parses left today" in r.data
    assert b"GymLLM shared model" in r.data


def test_site_review_uses_owner_key_and_counts_quota(site_user, site_app, fake_llm):
    from gymllm import quota

    fake_llm.queue(PARSED, PARSED)
    for _ in range(2):
        r = site_user.post("/review", data={"workout": "bench", "client_date": "2026-09-14"})
        assert r.status_code == 200 and b'name="entry-0-exercise"' in r.data
    assert len(fake_llm.calls) == 2
    assert all(c.provider == "groq" and c.api_key == "gsk-site" for c in fake_llm.configs)

    r = site_user.post("/review", data={"workout": "bench"})
    assert r.status_code == 200 and b"used today&#39;s 2 free parses" in r.data
    assert len(fake_llm.calls) == 2  # refused before any model call
    with site_app.app_context():
        assert quota.remaining(USER, 2) == 0
    r = site_user.get("/")
    assert b"0 of 2 free parses left today" in r.data and b"Come back tomorrow" in r.data


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
    assert r.status_code == 200 and b"Logged 12 entries" in r.data
    assert len(fake_llm.calls) == 10
    with site_app.app_context():
        tagged = [w.tags for w in Workout.query.order_by(Workout.id).all()]
        assert tagged[:10] == [f"t{i}" for i in range(10)] and tagged[10:] == ["", ""]


def test_site_option_only_offered_when_configured(site_user, logged_in):
    r = site_user.get("/settings")
    assert b'value="site" selected' in r.data and b"GymLLM shared model (free)" in r.data
    r = logged_in.get("/settings")
    assert b'value="site"' not in r.data
    r = logged_in.post("/settings", data={"provider": "site"})
    assert r.status_code == 400 and b"not set up on this server" in r.data


def test_site_settings_save_and_test(site_user, site_app, fake_llm):
    from gymllm import quota

    r = site_user.post("/settings", data={"provider": "site"}, follow_redirects=True)
    assert b"Saved. Using GymLLM shared model" in r.data
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
    assert b"in your browser" in r.data and b"free parses" not in r.data


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
    body = r.data.decode()
    assert r.status_code == 200 and "Logged 3 entries" in body
    assert "walking" in body and "3 miles" in body and "130 lbs" in body
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
    assert r.status_code == 200 and b"Logged 1 entry" in r.data
    with app.app_context():
        assert [w.weight for w in BodyWeight.query.all()] == ["129 lbs"]


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
    add_workout(date="2026-02-01", exercise="bench")
    add_cardio(date="2026-02-01", activity="walking", distance="3 miles")
    add_cardio(date="2026-02-03", activity="swimming", distance="20 laps")  # cardio-only day
    add_weight(date="2026-02-01", weight="130 lbs")
    body = logged_in.get("/").data.decode()
    body = body[body.index("Recent sessions") :]  # skip the exercise-search datalist
    assert "walking" in body and "3 miles" in body and "130 lbs" in body
    assert "swimming" in body and body.index("swimming") < body.index("bench")


def test_sessions_page_lists_and_edits_cardio_and_weights(
    logged_in, app, add_workout, add_cardio, add_weight
):
    add_workout(date="2026-03-10", exercise="bench")
    c = add_cardio(date="2026-03-10", activity="walking", distance="3 miles")
    theirs = add_cardio(date="2026-03-10", activity="not mine", user_email=OTHER)
    w = add_weight(date="2026-03-12", weight="130 lbs")

    body = logged_in.get("/search?today=2026-03-15").data.decode()
    assert f'name="cardio-{c}-distance" value="3 miles"' in body
    assert f'name="bw-{w}-weight" value="130 lbs"' in body
    assert "not mine" not in body and "3 rows" in body
    assert "1 cardio · 3 mi" in body and "weighed 130 lbs" in body

    r = logged_in.post(
        "/search",
        data={
            f"cardio-{c}-distance": "4 miles",
            f"cardio-{c}-activity": "",
            f"bwdelete-{w}": "1",
            f"cdelete-{theirs}": "1",
        },
        follow_redirects=True,
    )
    assert b"1 updated, 1 deleted" in r.data
    with app.app_context():
        assert (
            Cardio.query.get(c).distance == "4 miles" and Cardio.query.get(c).activity == "walking"
        )
        assert BodyWeight.query.get(w) is None
        assert Cardio.query.get(theirs) is not None

    # A bad date on any table blocks every change.
    r = logged_in.post(
        "/search",
        data={f"cardio-{c}-date": "soon", f"cardio-{c}-distance": "9 miles"},
        follow_redirects=True,
    )
    assert b"YYYY-MM-DD" in r.data
    with app.app_context():
        assert Cardio.query.get(c).distance == "4 miles"


def test_progress_and_exercises_show_cardio_and_weight(logged_in, add_cardio, add_weight):
    add_cardio(date="2026-03-12", activity="walking", distance="3 miles", duration="45 min")
    add_cardio(date="2026-03-13", activity="running", distance="2 mi", duration="20 min")
    add_weight(date="2026-03-09", weight="132 lbs")
    add_weight(date="2026-03-14", weight="130 lbs")

    body = logged_in.get("/progress?range=7d&today=2026-03-15").data.decode()
    assert "Nothing logged in this range" not in body
    assert "5 mi" in body and "2 activities" in body and "1 h 5 min" in body
    assert "130 lbs" in body and "-2 lbs since" in body
    assert (
        'aria-label="Body weight per day"' in body
        and 'aria-label="Cardio distance per day"' in body
    )
    assert '"weight": 132.0' in body and '"weight": 130.0' in body  # each on its own day
    assert 'aria-label="Exercises logged per day"' not in body  # no lifts in range

    body = logged_in.get("/progress?range=30d&by=week&today=2026-03-15").data.decode()
    assert 'aria-label="Body weight per week"' in body and "average of the week" in body
    assert "<th>Week</th>" in body and "Readings" in body

    # One reading still gets the chart (a single point on the period axis).
    body = logged_in.get("/progress?range=7d&today=2026-03-10").data.decode()
    assert 'aria-label="Body weight per day"' in body and "132 lbs" in body

    body = logged_in.get("/exercises?range=7d&today=2026-03-15").data.decode()
    assert "walking" in body and "running" in body and "3 mi" in body and "45 min" in body


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
    assert "130 lbs" in body and "not included when you share" in body
    assert 'href="/day/2026-03-01"' in body and 'href="/day/2026-03-12"' in body
    assert '<div class="stat-value">2</div>' in body  # exercises
    assert '<div class="stat-value">7</div>' in body  # 5 + 2 sets
    assert "4,625" in body  # 185 x 25
    assert "3 mi" in body and "45 min" in body
    assert 'href="/search?range=all&amp;by=day#day-2026-03-10"' in body


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
            "weight": "185 lbs",
            "sets_reps": "5, 5, 5, 5, 5",
            "pr": False,
        }
    ]
    assert share["cardio"] == [{"activity": "walking", "distance": "3 miles", "duration": "45 min"}]
    assert share["stats"]["sets"] == 5 and share["stats"]["cardio"] == "3 mi"
    assert "130" not in json.dumps(share)
    assert set(share) == {"date", "label", "stats", "lifts", "cardio"}


def test_day_page_marks_personal_records(logged_in, add_workout):
    add_workout(date="2026-03-01", weight="185 lbs")
    add_workout(date="2026-03-10", weight="190 lbs")
    add_workout(date="2026-03-10", exercise="pull up", weight="bodyweight")
    body = logged_in.get("/day/2026-03-10").data.decode()
    assert body.count('class="chip chip-pr"') == 1
    assert '"pr": true' in body
    assert 'class="chip chip-pr"' not in logged_in.get("/day/2026-03-01").data.decode()


def test_day_page_stacks_same_exercise_rows(logged_in, add_workout):
    add_workout(
        date="2026-03-10",
        exercise="barbell bench press",
        weight="135 lbs",
        sets="5",
        reps="5, 5, 5, 5, 5",
    )
    add_workout(
        date="2026-03-10", exercise="barbell bench press", weight="185 lbs", sets="3", reps="3, 3, 3"
    )
    add_workout(date="2026-03-10", exercise="squat", weight="225 lbs")
    body = logged_in.get("/day/2026-03-10").data.decode()
    assert body.count(">barbell bench press<") == 1  # one exercise cell, not one per weight
    assert 'rowspan="2"' in body
    assert "135 lbs" in body and "185 lbs" in body and "3, 3, 3" in body


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
    assert 'href="/day/2026-03-10"' in body and 'id="day-2026-03-10"' in body
    body = logged_in.get("/search?by=week&today=2026-03-15").data.decode()
    assert 'href="/day/' not in body and 'id="day-2026-03-09"' in body
    assert 'href="/day/2026-03-10"' in logged_in.get("/exercise/barbell bench press").data.decode()
    assert 'data-day-base="/day/"' in logged_in.get("/progress").data.decode()
    r = logged_in.post("/confirm", data={"date": "2026-03-11", "bodyweight": "130 lbs"})
    assert 'href="/day/2026-03-11"' in r.data.decode()
