import pytest

from gymllm import auth, create_app, quota, social
from gymllm.extensions import db
from gymllm.llm.client import BadOutputError, RateLimitError
from gymllm.models import BodyWeight, Cardio, Workout
from tests.conftest import OTHER, SITE_LLM, USER, base_test_config

TODAY = "2026-09-14"
BENCH = {
    "date": None,
    "exercises": [
        {"exercise": "bench press", "weight": "185 lbs", "sets": 3, "reps": [5, 5, 5], "notes": ""}
    ],
}


def token_for(app, email=USER, name="Tess Tester"):
    with app.test_request_context():
        return auth.issue_api_token(email, name)


def bearer(app, email=USER, name="Tess Tester"):
    return {"Authorization": f"Bearer {token_for(app, email, name)}"}


@pytest.fixture
def api(site_app):
    """Calls /api/v1 on the shared-model app as USER: api.get("/me"), api.post(...)."""

    class Api:
        app = site_app
        client = site_app.test_client()

        def call(self, method, path, email=USER, **kwargs):
            kwargs.setdefault("headers", bearer(site_app, email))
            return getattr(self.client, method)(f"/api/v1{path}", **kwargs)

        def get(self, path, **kwargs):
            return self.call("get", path, **kwargs)

        def post(self, path, **kwargs):
            return self.call("post", path, **kwargs)

        def put(self, path, **kwargs):
            return self.call("put", path, **kwargs)

    return Api()


def save(api, email=USER, **body):
    body = {"date": TODAY, "entries": BENCH["exercises"], **body}
    return api.post(f"/sessions?today={TODAY}", email=email, json=body)


# --- tokens -------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/me"),
        ("get", "/home"),
        ("post", "/parse"),
        ("post", "/sessions"),
        ("get", "/day/2026-09-14"),
        ("put", "/preferences"),
    ],
)
def test_no_token_is_401_json(client, method, path):
    r = getattr(client, method)(f"/api/v1{path}")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"


def test_bad_token_is_401(client):
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_token"


def test_token_signed_with_another_secret_is_401(app, client):
    other = create_app({**base_test_config(), "SECRET_KEY": "someone-else"})
    r = client.get("/api/v1/me", headers=bearer(other))
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_token"
    with other.app_context():
        db.session.remove()
        db.drop_all()


def test_expired_token_is_401(app, client, monkeypatch):
    headers = bearer(app)
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    monkeypatch.setattr(auth, "API_TOKEN_MAX_AGE", -1)
    r = client.get("/api/v1/me", headers=headers)
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "token_expired"


def test_cookie_session_does_not_authenticate_the_api(logged_in):
    assert logged_in.get("/api/v1/me").status_code == 401
    r = logged_in.post("/api/v1/sessions", json={"date": TODAY, "entries": BENCH["exercises"]})
    assert r.status_code == 401


def test_bad_bearer_token_never_falls_back_to_the_cookie(logged_in):
    r = logged_in.get("/", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")


def test_bearer_token_signs_in_on_the_website_too(app, client):
    with app.app_context():
        social.save_profile(USER, "tester", "Tess")
    with client.session_transaction() as s:
        s["llm"] = {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk", "base_url": ""}
    assert client.get("/", headers=bearer(app)).status_code == 200


def test_unknown_api_path_is_json_404(app, client):
    for r in (client.get("/api/v1/nope"), client.post("/api/v1/nope/deeper", json={})):
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    assert b"Page not found" in client.get("/nope", headers=bearer(app)).data  # the site's own


def test_api_post_needs_no_csrf_token(fake_llm):
    cfg = {**base_test_config(), "WTF_CSRF_ENABLED": True}
    app = create_app(cfg)
    client = app.test_client()
    r = client.put("/api/v1/preferences", headers=bearer(app), json={"weight_unit": "kg"})
    assert r.status_code == 200 and r.get_json() == {"weight_unit": "kg"}
    with client.session_transaction() as s:
        s["user_email"] = USER
    assert client.post("/weight-unit", data={"unit": "kg"}).status_code == 400  # still guarded
    with app.app_context():
        db.session.remove()
        db.drop_all()


# --- signing in -----------------------------------------------------------------


def google_app(claims=None, error=None):
    def verify(token, audience):
        assert audience == "ios-client-id"
        if error:
            raise error
        return claims

    cfg = {
        **base_test_config(),
        "GOOGLE_IOS_CLIENT_ID": "ios-client-id",
        "GOOGLE_ID_TOKEN_VERIFIER": verify,
    }
    return create_app(cfg)


def test_google_sign_in_issues_a_working_token():
    app = google_app({"email": USER, "email_verified": True, "name": "tess tester"})
    client = app.test_client()
    r = client.post("/api/v1/auth/google", json={"id_token": "from-google"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email"] == USER and body["user"]["first_name"] == "Tess"
    assert body["user"]["profile"] is None and body["user"]["quota"] is None
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.get_json() == body["user"]


@pytest.mark.parametrize(
    "claims,error,status,code",
    [
        (None, ValueError("wrong audience"), 401, "invalid_token"),
        (None, RuntimeError("no network"), 503, "google_unavailable"),
        ({"email": USER, "email_verified": False}, None, 401, "email_unverified"),
        ({"email_verified": True}, None, 401, "email_unverified"),
    ],
)
def test_google_sign_in_refusals(claims, error, status, code):
    client = google_app(claims, error).test_client()
    r = client.post("/api/v1/auth/google", json={"id_token": "x"})
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    assert "token" not in r.get_json()


def test_google_sign_in_needs_a_token_and_a_configured_client(client):
    r = client.post("/api/v1/auth/google", json={"id_token": "x"})
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "not_configured"
    google = google_app({}).test_client()
    for body in ({}, {"id_token": ""}, {"id_token": 5}, ["x"]):
        assert google.post("/api/v1/auth/google", json=body).status_code == 400


def test_dev_auth_issues_a_token_for_a_seeded_account(app, client):
    r = client.post("/api/v1/auth/dev", json={"slug": "alex"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email"] == "dev-alex@example.test"
    assert body["user"]["profile"]["handle"] == "alex"
    home = client.get("/api/v1/home", headers={"Authorization": f"Bearer {body['token']}"})
    assert home.status_code == 200 and home.get_json()["has_friends"] is True
    assert client.post("/api/v1/auth/dev", json={"slug": "nobody"}).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [{"IS_PRODUCTION": True}, {"SQLALCHEMY_DATABASE_URI": "postgresql://u:p@localhost/x"}],
)
def test_dev_auth_absent_in_production_and_off_sqlite(overrides, monkeypatch):
    # Nothing may touch the (unreachable) database: only the routing is under test.
    monkeypatch.setattr(db, "create_all", lambda: None)
    monkeypatch.setattr("gymllm.migrate.run", lambda: None)
    monkeypatch.setattr("gymllm.activity.touch", lambda email: None)
    app = create_app({**base_test_config(), **overrides})
    r = app.test_client().post("/api/v1/auth/dev", json={"slug": "alex"})
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"


# --- me and preferences ---------------------------------------------------------


def test_me(api, add_profile):
    with api.app.app_context():
        code = social.save_profile(USER, "tester", "Tess T", bio="lifts").invite_code
    body = api.get("/me").get_json()
    assert body == {
        "email": USER,
        "first_name": "Tess",
        "profile": {
            "handle": "tester",
            "name": "Tess T",
            "avatar_url": None,
            "bio": "lifts",
            "invite_url": f"http://localhost/invite/{code}",
        },
        "weight_unit": "lbs",
        "quota": {"left": 2, "limit": 2},
        "unseen": 0,
    }


def test_preferences(api):
    assert api.put("/preferences", json={"weight_unit": "kg"}).get_json() == {"weight_unit": "kg"}
    assert api.get("/me").get_json()["weight_unit"] == "kg"
    for body in ({"weight_unit": "stone"}, {}, "kg"):
        assert api.put("/preferences", json=body).status_code == 400
    assert api.get("/me").get_json()["weight_unit"] == "kg"


# --- parse ----------------------------------------------------------------------


def test_parse_returns_entries_and_spends_one_log(api, fake_llm):
    fake_llm.queue(
        {
            "date": "2026-09-13",
            "exercises": BENCH["exercises"],
            "cardio": [{"activity": "Run", "distance": "3 miles", "duration": "28 min"}],
            "bodyweight": 180,
        }
    )
    r = api.post(
        f"/parse?today={TODAY}", json={"text": " bench 185 3x5, ran 3 ", "weight_unit": "kg"}
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["date"] == "2026-09-13" and body["date_from_text"] is True
    assert body["entries"] == [
        {
            "exercise": "bench press",
            "weight": "185 lbs",
            "sets": "3",
            "reps": "5, 5, 5",
            "notes": "",
        }
    ]
    assert body["cardio"] == [
        {"activity": "run", "distance": "3 miles", "duration": "28 min", "notes": ""}
    ]
    assert body["bodyweight"] == "180" and body["default_title"] == "Sunday workout"
    assert body["visibility"] == "private" and body["first_log"] is True  # no profile yet
    assert body["weight_unit"] == "kg" and body["quota"] == {"left": 1, "limit": 2}
    system, user = fake_llm.calls[0]
    assert user == "bench 185 3x5, ran 3" and TODAY in system
    assert fake_llm.configs[0].api_key == SITE_LLM["api_key"]  # the owner's key, server side
    with api.app.app_context():
        assert Workout.query.count() == 0  # parsing saves nothing


def test_parse_defaults_to_today_and_friends_once_there_is_a_profile(api, fake_llm):
    with api.app.app_context():
        social.save_profile(USER, "tester", "Tess")
    fake_llm.queue(BENCH)
    body = api.post(f"/parse?today={TODAY}", json={"text": "bench", "routine_name": " Push  day "})
    body = body.get_json()
    assert body["date"] == TODAY and body["date_from_text"] is False
    assert body["visibility"] == "friends" and body["title"] == "Push day"
    assert body["default_title"] == "Monday workout"


def test_parse_quota_runs_out_with_app_wording(api, fake_llm):
    for _ in range(2):
        assert api.post("/parse", json={"text": "bench"}).status_code == 200
    r = api.post("/parse", json={"text": "bench"})
    assert r.status_code == 429
    error = r.get_json()["error"]
    assert error["code"] == "quota_exceeded" and "today's 2 free logs" in error["message"]
    assert "Settings" not in error["message"] and "model" not in error["message"]
    assert len(fake_llm.calls) == 2  # the third never reached the model


@pytest.mark.parametrize(
    "error,status,code",
    [
        (
            RateLimitError("Groq rate limit. Check your key on the Settings page."),
            503,
            "rate_limited",
        ),
        (BadOutputError("The model did not return JSON."), 422, "bad_output"),
        (RuntimeError("boom"), 502, "model_error"),
    ],
)
def test_parse_failure_refunds_the_log(api, fake_llm, error, status, code):
    fake_llm.error = error
    r = api.post("/parse", json={"text": "bench"})
    assert r.status_code == status
    body = r.get_json()["error"]
    assert body["code"] == code
    assert not any(word in body["message"] for word in ("Settings", "model", "key", "Groq"))
    with api.app.app_context():
        assert quota.remaining(USER, 2) == 2


def test_parse_needs_text_and_a_shared_model(api, app, client, fake_llm):
    for body in ({}, {"text": "   "}, {"text": 5}):
        r = api.post("/parse", json=body)
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "empty_text"
    r = client.post("/api/v1/parse", headers=bearer(app), json={"text": "bench"})  # no SITE_LLM
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "logging_unavailable"
    assert fake_llm.calls == []


# --- save -----------------------------------------------------------------------


def test_save_round_trips_and_shows_on_the_website(api):
    r = save(
        api,
        title="Push day",
        visibility="private",
        bodyweight="180",
        cardio=[{"activity": "Run", "distance": "3 miles", "duration": "28"}],
    )
    assert r.status_code == 201 and r.get_json() == {"date": TODAY, "session": 0}
    with api.app.app_context():
        lift = Workout.query.one()
        assert (lift.user_email, lift.exercise, lift.weight) == (
            USER,
            "barbell bench press",
            "185 lbs",
        )
        assert (lift.sets, lift.reps) == ("3", "5, 5, 5") and "chest" in lift.tags.split(";")
        assert Cardio.query.one().activity == "run"
        assert BodyWeight.query.one().weight == "180 lbs"
        assert social.visibilities(USER) == {TODAY: "private"}

    day = api.get(f"/day/{TODAY}?today={TODAY}").get_json()
    assert day["title"] == "Push day" and day["session"] == 0 and day["sessions"] == []
    assert [x["exercise"] for x in day["lifts"]] == ["barbell bench press"]
    assert day["lifts"][0]["pr"] is False and {"chest", "push"} <= set(day["lifts"][0]["tags"])
    assert day["lifts"][0]["sets_reps"] == "5, 5, 5" and day["lifts"][0]["notes"] == ""
    assert day["lines"] == [
        {"exercise": "barbell bench press", "detail": "185 lbs · 3×5", "parts": [], "pr": False}
    ]
    assert day["cardio"][0]["distance"] == "3 miles" and day["bodyweight"] == "180 lbs"
    assert day["stats"]["sets"] == 3 and day["stats"]["reps"] == 15
    assert day["previous"] is None and day["next"] is None and day["reactions"] is None

    # The same workout on the HTML day page, signed in with the cookie.
    with api.client.session_transaction() as s:
        s["user_email"] = USER
    html = api.client.get(f"/day/{TODAY}").data.decode()
    assert "Push day" in html and "Barbell bench press" in html and "185 lbs" in html


def test_second_save_the_same_day_is_a_second_session(api):
    save(api)
    r = save(api, entries=[{"exercise": "back squat", "weight": "225", "sets": "1", "reps": "5"}])
    assert r.get_json() == {"date": TODAY, "session": 1}
    day = api.get(f"/day/{TODAY}?session=1").get_json()
    assert [x["exercise"] for x in day["lifts"]] == ["barbell back squat"]
    assert day["lifts"][0]["weight"] == "225 lbs" and day["title"] == "Monday workout 2"
    assert day["sessions"] == [
        {"session": 0, "title": "Monday workout"},
        {"session": 1, "title": "Monday workout 2"},
    ]


@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"date": "14/09/2026"}, 400, "bad_date"),
        ({"date": ""}, 400, "bad_date"),
        ({"date": "2026-09-15"}, 422, "future_date"),
        ({"entries": [{"exercise": "bench press", "weight": "heavy"}]}, 422, "bad_weight"),
        ({"bodyweight": "light"}, 422, "bad_bodyweight"),
        ({"entries": [{"exercise": "  "}]}, 422, "nothing_to_save"),
        ({"entries": "bench"}, 400, "bad_request"),
        ({"entries": ["bench"]}, 400, "bad_request"),
        ({"cardio": [5]}, 400, "bad_request"),
        ({"title": 5}, 400, "bad_request"),
    ],
)
def test_save_refusals_save_nothing(api, body, status, code):
    r = save(api, **body)
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    with api.app.app_context():
        assert Workout.query.count() == 0 and BodyWeight.query.count() == 0


def test_save_reuses_the_websites_messages(api):
    r = save(api, entries=[{"exercise": "bench press", "weight": "heavy"}])
    assert r.get_json()["error"]["message"].startswith("“heavy” isn’t a weight.")


def test_save_caps_tag_calls_on_the_shared_model(api, fake_llm):
    from gymllm.logflow import MAX_SITE_TAG_CALLS

    entries = [{"exercise": f"made up move {i}", "sets": "1", "reps": "5"} for i in range(15)]
    assert save(api, entries=entries).status_code == 201
    assert len(fake_llm.calls) == MAX_SITE_TAG_CALLS


def test_save_works_without_a_shared_model(app, client):
    r = client.post(
        f"/api/v1/sessions?today={TODAY}",
        headers=bearer(app),
        json={"date": TODAY, "entries": [{"exercise": "made up move", "reps": "5"}]},
    )
    assert r.status_code == 201
    with app.app_context():
        assert Workout.query.one().tags == ""


# --- day ------------------------------------------------------------------------


def test_day_is_only_ever_your_own(api):
    save(api, entries=[{**BENCH["exercises"][0], "notes": "felt strong"}], bodyweight="180")
    mine = api.get(f"/day/{TODAY}").get_json()
    assert mine["lifts"][0]["notes"] == "felt strong" and mine["bodyweight"] == "180 lbs"

    theirs = api.get(f"/day/{TODAY}", email=OTHER)  # a stranger asking for the same date
    assert theirs.status_code == 200
    body = theirs.get_json()
    assert body["lifts"] == [] and body["cardio"] == [] and body["bodyweight"] is None
    assert "felt strong" not in theirs.get_data(as_text=True)


def test_day_neighbours_and_bad_dates(api):
    for when in ("2026-09-10", "2026-09-12", TODAY):
        save(api, date=when)
    body = api.get("/day/2026-09-12").get_json()
    assert body["previous"] == "2026-09-10" and body["next"] == TODAY
    empty = api.get("/day/2026-09-11").get_json()
    assert (
        empty["lifts"] == [] and empty["previous"] == "2026-09-10" and empty["next"] == "2026-09-12"
    )
    assert api.get("/day/yesterday").status_code == 404


# --- home, and what friends may see ------------------------------------------------


def test_home_for_a_new_user(api):
    body = api.get(f"/home?today={TODAY}").get_json()
    assert body["today"] == TODAY and len(body["week"]) == 7 and body["streak"] == 0
    assert [d["today"] for d in body["week"]] == [True] + [False] * 6  # the 14th is a Monday
    assert body["latest"] is None and body["recent"] == [] and body["friends"] == []
    assert body["has_logged"] is False and body["has_friends"] is False
    assert body["checklist"] == {"logged": False, "profile": False, "friends": False}
    assert body["quota"] == {"left": 2, "limit": 2}


def test_home_after_saving(api):
    n = save(api, title="Push day").get_json()["session"]
    body = api.get(f"/home?today={TODAY}&saved={TODAY}&session={n}").get_json()
    assert body["just_saved"] is True and body["first_save"] is True and body["has_logged"] is True
    assert body["latest"]["title"] == "Push day" and body["latest"]["stat_line"] == "3 sets"
    assert body["latest"]["icon_hint"].startswith("chest") and body["latest"]["reactions"] is None
    assert body["week"][0]["logged"] is True and body["week"][0]["sets"] == 3
    assert body["streak"] == 1
    assert body["recent"] == [
        {"date": TODAY, "session": 0, "title": "Push day", "summary": "Chest · 1 exercise"}
    ]
    assert body["checklist"] == {"logged": True, "profile": False, "friends": False}


def friends(api):
    with api.app.app_context():
        social.save_profile(USER, "tester", "Tess")
        social.save_profile(OTHER, "other", "Oli Other")
        social.befriend(USER, OTHER)


def test_friend_sees_lifts_but_never_notes_or_body_weight(api):
    friends(api)
    save(
        api,
        entries=[{**BENCH["exercises"][0], "notes": "left shoulder twinge"}],
        cardio=[{"activity": "run", "distance": "3 miles", "notes": "slow and sad"}],
        bodyweight="181.5",
    )
    r = api.get(f"/home?today={TODAY}", email=OTHER)
    body = r.get_json()
    card = body["friends"][0]
    assert card["owner"] == {"handle": "tester", "name": "Tess", "avatar_url": None, "bio": ""}
    assert card["lifts"][0]["exercise"] == "barbell bench press" and card["prs"] == 0
    assert "notes" not in card["lifts"][0] and "notes" not in card["cardio"][0]
    assert "bodyweight" not in card
    text = r.get_data(as_text=True)
    for private in ("twinge", "slow and sad", "181.5", USER):
        assert private not in text
    assert body["latest"] is None and body["has_friends"] is True


def test_private_day_and_strangers_see_nothing(api):
    friends(api)
    save(api, visibility="private")
    assert api.get(f"/home?today={TODAY}", email=OTHER).get_json()["friends"] == []

    with api.app.app_context():
        social.set_visibility(USER, TODAY, social.FRIENDS_ONLY)
        db.session.commit()
    assert len(api.get(f"/home?today={TODAY}", email=OTHER).get_json()["friends"]) == 1

    with api.app.app_context():
        social.unlink(USER, OTHER)
    body = api.get(f"/home?today={TODAY}", email=OTHER).get_json()
    assert body["friends"] == [] and body["has_friends"] is False


def test_reactions_on_your_own_card(api):
    friends(api)
    save(api)
    with api.app.app_context():
        social.toggle_kudos(OTHER, USER, TODAY)
        social.add_comment(OTHER, USER, TODAY, "Nice work!")
    for body in (
        api.get(f"/home?today={TODAY}").get_json()["latest"],
        api.get(f"/day/{TODAY}").get_json(),
    ):
        reactions = body["reactions"]
        assert reactions["kudos"] == 1 and reactions["kudoed"] is False
        (comment,) = reactions["comments"]
        assert comment["body"] == "Nice work!" and comment["can_delete"] is True
        assert comment["author"]["handle"] == "other" and comment["at"].endswith("Z")
    assert api.get("/me").get_json()["unseen"] == 2
    theirs = api.get(f"/home?today={TODAY}", email=OTHER).get_json()["friends"][0]["reactions"]
    assert theirs["kudoed"] is True and theirs["comments"][0]["can_delete"] is True
