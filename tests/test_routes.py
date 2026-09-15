import pytest

from gymllm import create_app
from gymllm.extensions import db
from gymllm.llm.client import AuthError
from gymllm.models import Workout
from tests.conftest import OTHER, USER, base_test_config


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
    assert body.count("2026-02-01") == 1  # one session heading per date


@pytest.mark.parametrize(
    "sets,reps,expected",
    [
        ("5", "5, 5, 5, 5, 5", "5×5"),
        ("3", "10, 8, 6", "3×10, 8, 6"),
        ("", "8, 8", "2×8"),
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
    r = logged_in.post("/settings/test", data={"provider": "ollama", "model": "llama3.2"})
    assert r.get_json()["ok"] is True
    r = logged_in.post(
        "/settings/test", data={"provider": "anthropic", "model": "x", "api_key": ""}
    )
    assert r.status_code == 400 and r.get_json()["ok"] is False
    # A blank key reuses the saved key for the same provider.
    fake_llm.queue({"ok": True})
    r = logged_in.post("/settings/test", data={"provider": "openai", "model": "x", "api_key": ""})
    assert r.status_code == 200 and r.get_json()["ok"] is True


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


def test_review_defaults_date_to_today_when_llm_gives_none(logged_in, fake_llm):
    fake_llm.queue({"date": None, "exercises": PARSED["exercises"]})
    r = logged_in.post("/review", data={"workout": "bench", "client_date": "2026-09-14"})
    assert b'value="2026-09-14"' in r.data


def test_review_shows_friendly_llm_error(logged_in, fake_llm):
    fake_llm.error = AuthError("OpenAI rejected the API key.")
    r = logged_in.post("/review", data={"workout": "bench"})
    assert r.status_code == 200 and b"rejected the API key" in r.data
    assert b'name="entry-0-exercise"' not in r.data


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
    assert '{"date": "2026-01-01", "weight": 185.0}' in body

    r = logged_in.get("/exercise/nothing here")
    assert r.status_code == 200 and b"No entries" in r.data


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
