import base64
import json
import time
from datetime import date

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import or_, select, text

from gymllm import account, apple_auth, auth, create_app, migrate, quota, rest, routines, social
from gymllm.extensions import db
from gymllm.llm.client import BadOutputError, RateLimitError
from gymllm.models import (
    AccountCutoff,
    BodyWeight,
    Cardio,
    RoutineBlock,
    SessionMeta,
    SessionVisibility,
    Workout,
)
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


def apple_app(claims=None, error=None):
    def verify(token, audience):
        assert audience == "com.levraapp.Levra"
        if error:
            raise error
        return claims

    return create_app({**base_test_config(), "APPLE_ID_TOKEN_VERIFIER": verify})


RELAY = "x7k2m9@privaterelay.appleid.com"


def test_apple_sign_in_issues_a_working_token_for_the_address_apple_gives():
    app = apple_app({"email": RELAY, "email_verified": "true", "sub": "001.abc"})
    client = app.test_client()
    r = client.post(
        "/api/v1/auth/apple", json={"identity_token": "from-apple", "name": " tess  tester "}
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email"] == RELAY and body["user"]["first_name"] == "Tess"
    assert body["user"]["profile"] is None
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.get_json() == body["user"]
    # Later sign-ins come without a name: Apple only gives it once.
    again = client.post("/api/v1/auth/apple", json={"identity_token": "from-apple"})
    assert again.status_code == 200 and again.get_json()["user"]["email"] == RELAY


def test_apple_sign_in_with_a_shared_address_is_that_addresss_account(add_workout):
    """Someone who lets Apple share their real address lands in the account that
    address already has; a relay address never matches one."""
    app = apple_app({"email": USER, "email_verified": True})
    with app.app_context():
        db.session.add(Workout(user_email=USER, date=TODAY, exercise="squat"))
        db.session.commit()
    client = app.test_client()
    token = client.post("/api/v1/auth/apple", json={"identity_token": "x"}).get_json()["token"]
    day = client.get(f"/api/v1/day/{TODAY}", headers={"Authorization": f"Bearer {token}"})
    assert day.status_code == 200 and day.get_json()["lifts"][0]["exercise"] == "squat"
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize(
    "claims,error,status,code",
    [
        (None, ValueError("wrong audience"), 401, "invalid_token"),
        (None, RuntimeError("no network"), 503, "apple_unavailable"),
        ({"email": RELAY, "email_verified": "false"}, None, 401, "email_unverified"),
        ({"email": RELAY}, None, 401, "email_unverified"),
        ({"email_verified": "true", "sub": "001.abc"}, None, 401, "email_unverified"),
    ],
)
def test_apple_sign_in_refusals(claims, error, status, code):
    client = apple_app(claims, error).test_client()
    r = client.post("/api/v1/auth/apple", json={"identity_token": "x"})
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    assert "token" not in r.get_json()


def test_apple_sign_in_needs_a_token():
    client = apple_app({}).test_client()
    for body in ({}, {"identity_token": ""}, {"identity_token": 5}, ["x"]):
        assert client.post("/api/v1/auth/apple", json=body).status_code == 400
    r = client.post("/api/v1/auth/apple", json={"identity_token": "x", "name": 5})
    assert r.status_code == 400


def apple_token(key, claims, kid="key-1", alg="RS256"):
    """A JWT as Apple would sign it, with our own key standing in for theirs."""
    part = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")  # noqa: E731
    signed = part({"alg": alg, "kid": kid}) + b"." + part(claims)
    signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    return (signed + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def test_apple_identity_token_verification(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    b64 = lambda n: base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode()  # noqa: E731
    jwks = {"key-1": {"kty": "RSA", "kid": "key-1", "n": b64(numbers.n), "e": b64(numbers.e)}}
    monkeypatch.setattr(apple_auth, "fetch_keys", lambda: jwks)
    monkeypatch.setattr(apple_auth, "_keys", {})
    good = {
        "iss": "https://appleid.apple.com",
        "aud": "com.levraapp.Levra",
        "exp": int(time.time()) + 600,
        "email": RELAY,
        "email_verified": "true",
    }
    verify = lambda token: apple_auth.verify_identity_token(token, "com.levraapp.Levra")  # noqa: E731

    assert verify(apple_token(key, good))["email"] == RELAY
    for bad in (
        apple_token(other, good),  # not Apple's signature
        apple_token(key, good, kid="key-2"),  # a key Apple doesn't publish
        apple_token(key, good, alg="none"),
        apple_token(key, {**good, "iss": "https://example.com"}),
        apple_token(key, {**good, "aud": "com.someone.Else"}),
        apple_token(key, {**good, "exp": int(time.time()) - 600}),
        apple_token(key, {k: v for k, v in good.items() if k != "exp"}),
        apple_token(key, good).rsplit(".", 1)[0] + ".AAAA",
        "not-a-token",
        "a.b.c",
    ):
        with pytest.raises(ValueError):
            verify(bad)


def test_dev_auth_issues_a_token_for_a_seeded_account(app, client):
    r = client.post("/api/v1/auth/dev", json={"slug": "alex"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email"] == "dev-alex@example.test"
    assert body["user"]["profile"]["handle"] == "alex"
    home = client.get("/api/v1/home", headers={"Authorization": f"Bearer {body['token']}"})
    assert home.status_code == 200 and home.get_json()["has_friends"] is True
    assert client.post("/api/v1/auth/dev", json={"slug": "nobody"}).status_code == 404


def test_dev_auth_can_issue_a_blank_account(app, client):
    r = client.post("/api/v1/auth/dev", json={"slug": "new-ab12"})
    user = r.get_json()["user"]
    assert user["email"] == "dev-new-ab12@example.test" and user["first_name"] == "Riley"
    assert user["profile"] is None
    for slug in ("new-", "new-AB", "new-" + "a" * 13, "new-a b"):
        assert client.post("/api/v1/auth/dev", json={"slug": slug}).status_code == 404


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


# --- Stage 3: progress, sessions, exercises ---------------------------------------


def delete(api, path, **kwargs):
    return api.call("delete", path, **kwargs)


def lift(exercise="bench press", weight="185 lbs", **more):
    return {"exercise": exercise, "weight": weight, "sets": 3, "reps": [5, 5, 5], **more}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/progress"),
        ("get", "/sessions"),
        ("get", "/search"),
        ("get", "/exercises"),
        ("get", "/exercises/bench"),
        ("put", f"/day/{TODAY}/sessions/0"),
        ("delete", f"/day/{TODAY}/sessions/0"),
        ("post", "/rest/rules"),
        ("delete", "/rest/rules/1"),
        ("put", f"/rest/day/{TODAY}"),
    ],
)
def test_stage_3_endpoints_need_a_token(client, method, path):
    r = getattr(client, method)(f"/api/v1{path}")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"


def test_progress_for_a_new_user(api):
    body = api.get(f"/progress?today={TODAY}").get_json()
    assert body["range"] == "all" and body["by"] == "month" and body["start"] is None
    assert body["total"] == 0 and body["totals"]["sessions"] == 0 and body["streak"] == 0
    assert body["bodyweight"] is None and body["lifts"] == [] and body["prs"] == []
    assert len(body["week"]["days"]) == 7 and body["week"]["start"] == TODAY
    assert body["week"]["is_this_week"] is True and body["week"]["next"] is None
    assert body["weight_unit"] == "lbs"


def test_progress_overview(api):
    save(api, date="2026-09-07", entries=[lift(weight="175 lbs")], bodyweight="182")
    save(
        api,
        entries=[lift()],
        cardio=[{"activity": "run", "distance": "3 miles", "duration": "30 min"}],
        bodyweight="180",
    )
    body = api.get(f"/progress?today={TODAY}&range=30d&by=week").get_json()
    assert body["range"] == "30d" and body["by"] == "week" and body["start"] == "2026-08-16"
    totals = body["totals"]
    assert totals["sessions"] == 2 and totals["entries"] == 2 and totals["cardio"] == 1
    assert totals["cardio_distance"] == "3 mi" and totals["cardio_minutes"]
    assert body["streak"] == 2 and body["per_period"][-1]["current"] is True
    (pr,) = body["prs"]
    assert pr["exercise"] == "barbell bench press" and pr["date"] == TODAY
    assert pr["value"] == 185 and pr["previous"] == 175
    (progress,) = body["lifts"]
    assert progress["first"] == 175 and progress["latest"] == 185 and progress["change"] == 10
    assert [p["date"] for p in progress["series"]] == ["2026-09-07", TODAY]
    bw = body["bodyweight"]
    assert bw["latest"] == "180 lbs" and bw["change"] == -2 and bw["chart_unit"] == "lbs"
    assert body["tags"][0]["tag"] == "chest" and body["top_exercises"][0]["entries"] == 2
    assert body["week"]["days"][0]["logged"] is True

    last = api.get(f"/progress?today={TODAY}&week=2026-09-09").get_json()["week"]
    assert last["start"] == "2026-09-07" and last["next"] == TODAY
    assert last["is_this_week"] is False and last["days"][0]["bodyweight"] == "182 lbs"
    ahead = api.get(f"/progress?today={TODAY}&week=2027-01-01").get_json()["week"]
    assert ahead["start"] == TODAY  # never a week still to come


def test_sessions_list_and_search(api):
    save(api, date="2026-08-30", entries=[lift("squat", "225 lbs")], title="Leg day")
    save(api, entries=[lift(notes="paused reps")], bodyweight="180")
    save(api, entries=[], cardio=[{"activity": "run", "distance": "3 miles"}])
    body = api.get(f"/sessions?today={TODAY}").get_json()
    assert body["shown"] == 3 and body["total"] == 4 and body["range"] == "all"
    assert [m["label"] for m in body["months"]] == ["September 2026", "August 2026"]
    run, bench = body["months"][0]["days"]
    assert run["session"] == 1 and run["bodyweight"] is None
    assert run["lines"] == [{"name": "run", "detail": "3 miles", "parts": [], "pr": False}]
    assert bench["session"] == 0 and bench["bodyweight"] == "180 lbs"
    assert bench["lines"][0]["detail"] == "185 lbs · 3×5" and bench["icon_hint"].startswith("chest")
    assert bench["icon"] == "push"
    assert body["months"][1]["days"][0]["title"] == "Leg day"

    def found(query):
        hits = api.get(f"/search?today={TODAY}&{query}").get_json()
        return [d["title"] for m in hits["months"] for d in m["days"]], hits["shown"]

    assert found("q=leg") == (["Leg day"], 1)
    assert found("q=PAUSED+bench")[1] == 1  # every word, any case, notes included
    assert found("q=august")[1] == 1 and found("q=deadlift") == ([], 0)
    assert found("range=7d")[1] == 2


def test_exercises_and_one_exercise(api):
    save(api, date="2026-09-07", entries=[lift(weight="175 lbs", notes="easy")])
    save(api, entries=[lift(), lift("squat", "bodyweight")], cardio=[{"activity": "run"}])
    body = api.get(f"/exercises?today={TODAY}").get_json()
    assert body["total"] == 4 and body["cardio"][0]["activity"] == "run"
    bench = next(e for e in body["exercises"] if e["exercise"] == "barbell bench press")
    assert bench["sessions"] == 2 and bench["best"] == "185 lbs" and bench["spark"] == [175, 185]
    assert bench["first"] == "2026-09-07" and bench["last"] == TODAY

    one = api.get(f"/exercises/Barbell%20Bench%20Press?today={TODAY}").get_json()
    assert one["name"] == "barbell bench press" and one["total"] == 2 and one["sessions"] == 2
    assert one["best"] == {"value": 185, "weight": "185 lbs", "date": TODAY}
    assert one["tags"][0] == "chest" and one["progress"]["change"] == 10
    assert [e["date"] for e in one["entries"]] == [TODAY, "2026-09-07"]
    assert one["entries"][1]["notes"] == "easy" and one["entries"][0]["sets_reps"] == "5, 5, 5"
    week = api.get(f"/exercises/barbell bench press?today={TODAY}&range=7d").get_json()
    assert week["total"] == 2 and len(week["entries"]) == 1 and week["progress"] is None

    assert api.get("/exercises/zercher%20squat").status_code == 404
    # Someone else asking for yours gets nothing.
    assert api.get("/exercises/barbell%20bench%20press", email=OTHER).status_code == 404
    assert api.get(f"/exercises?today={TODAY}", email=OTHER).get_json()["exercises"] == []
    assert api.get(f"/sessions?today={TODAY}", email=OTHER).get_json()["months"] == []
    assert api.get(f"/progress?today={TODAY}", email=OTHER).get_json()["total"] == 0


# --- Stage 3: editing one workout -------------------------------------------------


def edit(api, body, when=TODAY, n=0, **kwargs):
    return api.put(f"/day/{when}/sessions/{n}?today={TODAY}", json=body, **kwargs)


def test_day_says_what_the_editor_starts_from(api):
    save(api, visibility="private")
    save(api)
    first, second = (api.get(f"/day/{TODAY}?session={n}").get_json() for n in (0, 1))
    assert first["default_title"] == "Monday workout" and first["edits_bodyweight"] is True
    assert second["default_title"] == "Monday workout 2" and second["edits_bodyweight"] is False
    assert first["visibility"] == "friends"  # the day's latest save decides


def test_edit_changes_adds_and_removes_rows(api):
    save(
        api,
        entries=[lift(), lift("squat", "225 lbs")],
        cardio=[{"activity": "run", "distance": "3 miles"}],
    )
    day = api.get(f"/day/{TODAY}").get_json()
    bench, squat = day["lifts"]
    (run,) = day["cardio"]
    r = edit(
        api,
        {
            "title": "Heavy day",
            "visibility": "private",
            "bodyweight": "181",
            "lifts": [
                {"id": bench["id"], "weight": "190", "notes": " grind "},
                {"id": squat["id"], "delete": True},
                lift("overhead press", "95 lbs"),
                {"exercise": "  "},  # an empty new row is dropped
            ],
            "cardio": [{"id": run["id"], "duration": "25"}, {"activity": "row", "distance": "2k"}],
        },
    )
    assert r.status_code == 200
    assert r.get_json() == {"date": TODAY, "session": 0, "removed": False, "weigh_in_left": False}
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["title"] == "Heavy day" and day["visibility"] == "private"
    assert day["bodyweight"] == "181 lbs"
    assert [(x["exercise"], x["weight"]) for x in day["lifts"]] == [
        ("barbell bench press", "190 lbs"),
        ("barbell overhead press", "95 lbs"),
    ]
    assert day["lifts"][0]["notes"] == "grind" and day["lifts"][1]["tags"]
    assert [(c["activity"], c["duration"]) for c in day["cardio"]] == [
        ("run", "25 min"),
        ("row", ""),
    ]
    # And the website shows the same day.
    with api.app.test_client() as web:
        with web.session_transaction() as s:
            s["user_email"] = USER
        page = web.get(f"/day/{TODAY}").get_data(as_text=True)
    assert "Heavy day" in page and "190 lbs" in page


def test_edit_only_touches_what_it_names(api):
    save(api, title="Push day", bodyweight="180", visibility="private")
    assert edit(api, {}).status_code == 200
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["title"] == "Push day" and day["bodyweight"] == "180 lbs"
    assert day["visibility"] == "private" and len(day["lifts"]) == 1
    edit(api, {"title": "", "bodyweight": ""})
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["title"] == "Monday workout" and day["bodyweight"] is None


def test_edit_moves_a_workout_with_its_name_and_reactions(api):
    friends(api)
    save(api, title="Push day", bodyweight="180")
    save(api, date="2026-09-12")
    with api.app.app_context():
        social.toggle_kudos(OTHER, USER, TODAY)
        social.add_comment(OTHER, USER, TODAY, "Nice work!")
    r = edit(api, {"date": "2026-09-12"})
    assert r.get_json() == {
        "date": "2026-09-12",
        "session": 1,
        "removed": False,
        "weigh_in_left": False,
    }
    moved = api.get("/day/2026-09-12?session=1").get_json()
    assert moved["title"] == "Push day" and moved["reactions"]["kudos"] == 1
    assert moved["reactions"]["comments"][0]["body"] == "Nice work!"
    assert [s["session"] for s in moved["sessions"]] == [0, 1]
    assert api.get(f"/day/{TODAY}").get_json()["lifts"] == []
    with api.app.app_context():  # the weigh-in went along: nothing else was on that day
        (reading,) = BodyWeight.query.filter_by(user_email=USER).all()
        assert reading.date == "2026-09-12"


@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"date": "tomorrow"}, 400, "bad_date"),
        ({"date": "2026-09-15"}, 422, "future_date"),
        ({"bodyweight": "light"}, 422, "bad_bodyweight"),
        ({"lifts": [{"id": 1, "weight": "heavy"}]}, 422, "bad_weight"),
        ({"lifts": [{"id": 1, "delete": True}, lift(weight="heavy")]}, 422, "bad_weight"),
        ({"lifts": [{"id": 999, "weight": "1"}]}, 400, "bad_request"),
        ({"lifts": [{"id": 1, "weight": 190}]}, 400, "bad_request"),
        ({"lifts": "all of them"}, 400, "bad_request"),
        ({"title": 7}, 400, "bad_request"),
    ],
)
def test_edit_refusals_change_nothing(api, body, status, code):
    save(api, title="Push day", bodyweight="180")
    r = edit(api, body)
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["title"] == "Push day" and day["bodyweight"] == "180 lbs"
    assert [(x["id"], x["weight"]) for x in day["lifts"]] == [(1, "185 lbs")]


def test_edit_cannot_move_onto_another_weigh_in(api):
    save(api, bodyweight="180")
    save(api, date="2026-09-12", bodyweight="181")
    r = edit(api, {"date": "2026-09-12"})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "weigh_in_taken"
    assert len(api.get(f"/day/{TODAY}").get_json()["lifts"]) == 1


def test_edit_and_delete_are_only_ever_your_own(api):
    save(api)
    assert edit(api, {"title": "Mine now"}, email=OTHER).status_code == 404
    assert delete(api, f"/day/{TODAY}/sessions/0", email=OTHER).status_code == 404
    assert edit(api, {}, n=3).status_code == 404 and edit(api, {}, when="soon").status_code == 404
    with api.app.app_context():
        assert Workout.query.filter_by(user_email=USER).count() == 1


def test_delete_removes_the_workout_and_what_hung_on_it(api):
    friends(api)
    save(api, title="Push day")
    with api.app.app_context():
        social.toggle_kudos(OTHER, USER, TODAY)
    r = delete(api, f"/day/{TODAY}/sessions/0")
    assert r.status_code == 200
    assert r.get_json() == {"date": TODAY, "session": 0, "removed": True, "weigh_in_left": False}
    assert api.get(f"/sessions?today={TODAY}").get_json()["shown"] == 0
    assert api.get(f"/home?today={TODAY}", email=OTHER).get_json()["friends"] == []
    assert delete(api, f"/day/{TODAY}/sessions/0").status_code == 404
    save(api)  # a new workout that day starts clean
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["title"] == "Monday workout" and day["reactions"]["kudos"] == 0


def test_delete_keeps_the_days_weigh_in(api):
    save(api, bodyweight="180", cardio=[{"activity": "run"}])
    body = delete(api, f"/day/{TODAY}/sessions/0").get_json()
    assert body["removed"] is True and body["weigh_in_left"] is True
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["lifts"] == [] and day["cardio"] == [] and day["bodyweight"] == "180 lbs"
    with api.app.app_context():
        assert Cardio.query.count() == 0


# --- Stage 3: rest days -----------------------------------------------------------


def test_rest_rules(api):
    r = api.post("/rest/rules", json={"kind": "weekdays", "weekdays": [6, 0, 9]})
    assert r.status_code == 201
    (rule,) = r.get_json()["rest_rules"]
    assert rule["kind"] == "weekdays" and rule["weekdays"] == [0, 6]
    r = api.post(f"/rest/rules?today={TODAY}", json={"kind": "interval", "interval_days": 4})
    every = r.get_json()["rest_rules"][1]
    assert every["interval_days"] == 4 and every["anchor_date"] == TODAY

    progress = api.get(f"/progress?today={TODAY}&week=2026-09-07").get_json()
    assert len(progress["rest_rules"]) == 2
    assert [d["rest"] for d in progress["week"]["days"]] == [True, False, False, True] + [
        False,
        False,
        True,
    ]

    for body in ({"kind": "weekdays"}, {"kind": "interval", "interval_days": 1}, {"kind": "x"}):
        refused = api.post("/rest/rules", json=body)
        assert refused.status_code == 422 and refused.get_json()["error"]["code"] == "bad_rest_rule"
    assert delete(api, f"/rest/rules/{rule['id']}", email=OTHER).status_code == 404
    left = delete(api, f"/rest/rules/{rule['id']}").get_json()["rest_rules"]
    assert [x["id"] for x in left] == [every["id"]]


def test_rest_day_by_hand(api):
    day = "2026-09-10"
    r = api.put(f"/rest/day/{day}?today={TODAY}", json={"rest": True})
    assert r.status_code == 200 and r.get_json() == {"date": day, "rest": True}
    week = api.get(f"/progress?today={TODAY}&week={day}").get_json()["week"]["days"]
    assert [d["rest"] for d in week if d["date"] == day] == [True]
    assert api.put(f"/rest/day/{day}?today={TODAY}").get_json()["rest"] is False  # flips

    save(api)
    for when, status in (("2026-09-15", 422), (TODAY, 422), ("someday", 404)):
        assert api.put(f"/rest/day/{when}?today={TODAY}", json={"rest": True}).status_code == status
    assert api.put(f"/rest/day/{day}?today={TODAY}", json={"rest": "yes"}).status_code == 400


# --- Stage 4: friends -----------------------------------------------------------

STRANGER = "stranger@example.com"


def add_profile(api, email=USER, handle="tester", name=None):
    """A profile in the app `api` calls (conftest's add_profile fills another one)."""
    with api.app.app_context():
        return social.save_profile(email, handle, name or handle.title()).invite_code


def add_workout(api, user_email=USER, **kwargs):
    row = {"exercise": "barbell bench press", "sets": "3", "reps": "5, 5, 5", "tags": "chest;push"}
    with api.app.app_context():
        db.session.add(Workout(user_email=user_email, **{**row, **kwargs}))
        db.session.commit()


def stranger(api):
    add_profile(api, STRANGER, "stranger", "Sal Stranger")


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/profile"),
        ("put", "/profile"),
        ("post", "/profile/invite-reset"),
        ("get", "/u/other"),
        ("get", "/u/other/compare"),
        ("get", "/friends"),
        ("post", "/friends/request/other"),
        ("get", "/invite/abc"),
        ("post", "/invite/abc"),
        ("get", "/feed"),
        ("post", f"/kudos/other/{TODAY}/0"),
        ("post", f"/comments/other/{TODAY}/0"),
        ("delete", "/comments/1"),
    ],
)
def test_stage_4_endpoints_need_a_token(client, method, path):
    r = getattr(client, method)(f"/api/v1{path}")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/profile/invite-reset"),
        ("get", "/u/other"),
        ("get", "/u/other/compare"),
        ("get", "/friends"),
        ("post", "/friends/request/other"),
        ("get", "/invite/abc"),
        ("post", "/invite/abc"),
        ("get", "/feed"),
        ("post", f"/kudos/other/{TODAY}/0"),
        ("post", f"/comments/other/{TODAY}/0"),
        ("delete", "/comments/1"),
    ],
)
def test_no_profile_is_its_own_error(api, method, path):
    r = api.call(method, path, json={})
    assert r.status_code == 403
    assert r.get_json()["error"] == {
        "code": "profile_required",
        "message": "Set up your profile first.",
    }


def test_profile_setup_starts_from_a_suggestion(api):
    code = add_profile(api, OTHER, "tess_tester", "Oli Other")
    body = api.get(f"/profile?invite={code}").get_json()
    assert body["profile"] is None
    # "tess_tester" is taken, so the suggestion moves on.
    assert body["suggested"] == {"handle": "tess_tester2", "name": "Tess Tester", "bio": ""}
    assert body["inviter"]["handle"] == "tess_tester"
    assert OTHER not in str(body)


def test_profile_create_then_edit(api):
    r = api.put("/profile", json={"handle": "@Tess", "name": " Tess T ", "bio": "Lifts."})
    body = r.get_json()
    assert r.status_code == 201 and body["created"] is True
    assert body["profile"]["handle"] == "tess" and body["profile"]["name"] == "Tess T"
    assert body["profile"]["bio"] == "Lifts." and "/invite/" in body["profile"]["invite_url"]
    assert api.get("/me").get_json()["profile"]["handle"] == "tess"

    r = api.put("/profile", json={"handle": "tess", "name": "", "bio": ""})
    assert r.status_code == 200 and r.get_json()["created"] is False
    assert r.get_json()["profile"]["name"] == "tess"  # no name falls back to the handle
    got = api.get("/profile").get_json()
    assert got["profile"]["handle"] == "tess" and got["suggested"]["handle"] == "tess"
    assert got["inviter"] is None


def test_profile_takes_the_google_picture_from_the_token(api):
    with api.app.test_request_context():
        token = auth.issue_api_token(USER, "Tess", "https://pics.example/t.png")
    r = api.put("/profile", json={"handle": "tess"}, headers={"Authorization": f"Bearer {token}"})
    assert r.get_json()["profile"]["avatar_url"] == "https://pics.example/t.png"


@pytest.mark.parametrize(
    "body,status,code,says",
    [
        ({"handle": "ab"}, 422, "bad_handle", "3 to 20 characters"),
        ({"handle": "has space"}, 422, "bad_handle", "3 to 20 characters"),
        ({"handle": "admin"}, 422, "bad_handle", "reserved"),
        ({"handle": "other"}, 422, "bad_handle", "taken"),
        ({}, 422, "bad_handle", "3 to 20 characters"),
        ({"handle": 7}, 400, "bad_request", "handle must be text"),
        ({"handle": "fine", "bio": ["x"]}, 400, "bad_request", "bio must be text"),
    ],
)
def test_profile_refusals_save_nothing(api, body, status, code, says):
    add_profile(api, OTHER, "other")
    r = api.put("/profile", json=body)
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    assert says in r.get_json()["error"]["message"]
    assert api.get("/me").get_json()["profile"] is None


def test_invite_reset_kills_the_old_link(api):
    old = add_profile(api)
    add_profile(api, OTHER, "other")
    new = api.post("/profile/invite-reset").get_json()["invite_url"].rsplit("/", 1)[1]
    assert new != old
    assert api.get(f"/invite/{old}", email=OTHER).status_code == 404
    assert api.get(f"/invite/{new}", email=OTHER).get_json()["relationship"] == "none"


def test_friend_requests_from_search_to_unfriending(api):
    stranger(api)
    with api.app.app_context():
        social.save_profile(USER, "tester", "Tess")
        social.save_profile(OTHER, "other", "Oli Other")

    found = api.get("/friends?q=@OT").get_json()
    assert found["results"] == [
        {
            "handle": "other",
            "name": "Oli Other",
            "avatar_url": None,
            "bio": "",
            "relationship": "none",
        }
    ]
    assert api.get("/friends?q=tester").get_json()["results"] == []  # never yourself

    r = api.post("/friends/request/other").get_json()
    assert r["relationship"] == "outgoing" and r["message"] == "Friend request sent to Oli Other."
    assert [p["handle"] for p in api.get("/friends").get_json()["outgoing"]] == ["other"]
    theirs = api.get("/friends", email=OTHER).get_json()
    assert [p["handle"] for p in theirs["incoming"]] == ["tester"] and theirs["friends"] == []
    assert api.get("/me", email=OTHER).get_json()["unseen"] == 1

    r = api.post("/friends/accept/tester", email=OTHER).get_json()
    assert r["relationship"] == "friends" and r["message"] == "You and Tess are now friends."
    mine = api.get("/friends").get_json()
    assert [p["handle"] for p in mine["friends"]] == ["other"] and mine["outgoing"] == []
    assert "/invite/" in mine["invite_url"]

    assert api.post("/friends/remove/other").get_json()["relationship"] == "none"
    assert api.get("/friends", email=OTHER).get_json()["friends"] == []

    # Asking someone who already asked you makes you friends at once.
    api.post("/friends/request/tester", email=STRANGER)
    r = api.post("/friends/request/stranger").get_json()
    assert r["relationship"] == "friends"
    # Declining and cancelling forget the pair.
    api.post("/friends/request/other")
    assert api.post("/friends/cancel/other").get_json()["relationship"] == "none"
    api.post("/friends/request/other")
    assert api.post("/friends/decline/tester", email=OTHER).get_json()["relationship"] == "none"

    assert api.post("/friends/poke/other").status_code == 404
    assert api.post("/friends/request/nobody").status_code == 404
    assert api.post("/friends/request/tester").get_json()["relationship"] == "self"
    for payload in (found, mine, theirs):
        assert "@example.com" not in str(payload)


def test_invite_link_makes_friends_at_once(api):
    add_profile(api)
    code = add_profile(api, OTHER, "other", "Oli Other")
    r = api.get(f"/invite/{code}").get_json()
    assert r["person"]["name"] == "Oli Other" and r["relationship"] == "none"
    assert r["message"] == ""
    r = api.post(f"/invite/{code}").get_json()
    assert r["relationship"] == "friends" and r["message"] == "You and Oli Other are now friends."
    assert api.post(f"/invite/{code}").get_json()["message"] == ""  # already friends
    assert api.get(f"/invite/{code}", email=OTHER).get_json()["relationship"] == "self"
    r = api.get("/invite/not-a-code")
    assert r.status_code == 404 and "invite link" in r.get_json()["error"]["message"]


PRIVATE_WORDS = ("twinge", "slow and sad", "181.5", "@example.com")


def save_with_secrets(api, **more):
    return save(
        api,
        entries=[{**BENCH["exercises"][0], "notes": "left shoulder twinge"}],
        cardio=[{"activity": "run", "distance": "3 miles", "notes": "slow and sad"}],
        bodyweight="181.5",
        **more,
    )


def test_feed_is_friends_workouts_without_notes_or_body_weight(api):
    friends(api)
    save_with_secrets(api)
    r = api.get(f"/feed?today={TODAY}", email=OTHER)
    body = r.get_json()
    (card,) = body["cards"]
    assert card["owner"]["handle"] == "tester" and card["date"] == TODAY
    assert card["lifts"][0]["exercise"] == "barbell bench press"
    assert card["reactions"] == {"kudos": 0, "kudoed": False, "comments": []}
    assert "notes" not in card["lifts"][0] and "notes" not in card["cardio"][0]
    assert "bodyweight" not in card
    assert body["next_before"] is None and body["has_friends"] is True
    for private in PRIVATE_WORDS:
        assert private not in r.get_data(as_text=True)
    # Your own workouts are not in your feed.
    assert api.get(f"/feed?today={TODAY}").get_json()["cards"] == []


def test_feed_hides_private_days_and_pages_by_date(api):
    friends(api)
    for day in range(1, 26):
        add_workout(api, date=f"2026-08-{day:02d}")
    with api.app.app_context():
        social.set_visibility(USER, "2026-08-25", social.PRIVATE)
        db.session.commit()
    first = api.get("/feed", email=OTHER).get_json()
    assert [c["date"] for c in first["cards"]][:2] == ["2026-08-24", "2026-08-23"]
    assert len(first["cards"]) == 20 and first["next_before"] == "2026-08-05"
    rest = api.get("/feed?before=2026-08-05", email=OTHER).get_json()
    assert [c["date"] for c in rest["cards"]] == [f"2026-08-0{d}" for d in (4, 3, 2, 1)]
    assert rest["next_before"] is None
    assert len(api.get("/feed?before=nonsense", email=OTHER).get_json()["cards"]) == 20


def test_profile_of_a_friend_a_stranger_and_yourself(api):
    friends(api)
    stranger(api)
    save_with_secrets(api)
    save(api, date="2026-09-10", visibility="private", entries=[lift("squat", "225 lbs")])

    r = api.get(f"/u/tester?today={TODAY}", email=OTHER)
    body = r.get_json()
    assert body["person"]["name"] == "Tess" and body["relationship"] == "friends"
    assert body["visible"] is True and body["friend_count"] == 1
    assert body["total"] == 2 and body["streak"] == 1  # the private day isn't counted
    assert body["last_30"] == {"sessions": 1, "sets": 3, "cardio_minutes": 0}
    assert [f["exercise"] for f in body["favourites"]] == ["barbell bench press"]
    assert [c["date"] for c in body["cards"]] == [TODAY]
    assert "notes" not in body["cards"][0]["lifts"][0]
    monday = body["week"][0]
    assert monday["date"] == TODAY and monday["logged"] is True and "bodyweight" not in monday
    for private in (*PRIVATE_WORDS, "squat"):
        assert private not in r.get_data(as_text=True)

    r = api.get("/u/tester", email=STRANGER)
    assert r.get_json() == {
        "person": {"handle": "tester", "name": "Tess", "avatar_url": None, "bio": ""},
        "relationship": "none",
        "friend_count": 1,
        "visible": False,
    }

    r = api.get(f"/u/@Tester?today={TODAY}")
    mine = r.get_json()
    assert mine["relationship"] == "self" and mine["total"] == 3
    assert len(mine["cards"]) == 2
    # Even your own profile is the friends' view of you: no weigh-in, no notes.
    for private in PRIVATE_WORDS:
        assert private not in r.get_data(as_text=True)
    assert api.get("/u/nobody").status_code == 404


def test_profile_lists_recent_bests_without_the_rows_behind_them(api):
    friends(api)
    add_workout(api, date="2026-09-01", weight="185 lbs", notes="felt heavy")
    add_workout(api, date="2026-09-08", weight="195 lbs", notes="felt heavy")
    r = api.get(f"/u/tester?today={TODAY}", email=OTHER)
    assert r.get_json()["prs"] == [
        {
            "exercise": "barbell bench press",
            "date": "2026-09-08",
            "session": 0,
            "weight": "195 lbs",
            "value": 195.0,
            "previous": 185.0,
        }
    ]
    assert "felt heavy" not in r.get_data(as_text=True)


def test_compare_is_for_friends_only(api):
    friends(api)
    stranger(api)
    add_workout(api, date="2026-09-10", weight="185 lbs", notes="felt heavy")
    add_workout(api, date="2026-09-11", weight="205 lbs", user_email=OTHER)
    add_workout(api, date="2026-09-12", exercise="deadlift", weight="315 lbs", user_email=OTHER)
    with api.app.app_context():
        social.set_visibility(OTHER, "2026-09-12", social.PRIVATE)
        db.session.add(BodyWeight(user_email=OTHER, date="2026-09-11", weight="181.5 lbs"))
        db.session.commit()

    r = api.get(f"/u/other/compare?today={TODAY}&range=7d")
    body = r.get_json()
    assert body["range"] == "7d" and body["empty"] is False
    assert body["me"]["handle"] == "tester" and body["other"]["handle"] == "other"
    sessions = body["totals"][0]
    assert sessions == {"label": "Sessions", "mine": 1, "theirs": 1, "lead": None, "units": None}
    (shared,) = body["shared"]
    assert shared["exercise"] == "barbell bench press" and shared["lead"] == "theirs"
    assert shared["diff"] == 20 and shared["unit"] == "lbs"
    assert shared["mine"]["text"] == "185 lbs" and shared["theirs"]["text"] == "205 lbs"
    assert [f["exercise"] for f in body["favourites"]["theirs"]] == ["barbell bench press"]
    assert body["favourites"]["mine"][0]["shared"] is True
    assert len(body["weekly"]) == 12 and body["muscles"][0]["tag"] in ("chest", "push")
    for private in ("deadlift", "181.5", "felt heavy", "@example.com"):
        assert private not in r.get_data(as_text=True)
    assert api.get("/u/other/compare?range=nonsense").get_json()["range"] == "30d"

    assert api.get("/u/tester/compare").status_code == 404  # not with yourself
    assert api.get("/u/stranger/compare").status_code == 404
    assert api.get("/u/tester/compare", email=STRANGER).status_code == 404


def test_high_fives_toggle_and_are_for_friends_workouts(api):
    friends(api)
    stranger(api)
    save(api)
    path = f"/kudos/tester/{TODAY}/0"
    assert api.post(path, email=OTHER).get_json() == {"count": 1, "mine": True}
    assert api.get("/feed", email=OTHER).get_json()["cards"][0]["reactions"]["kudoed"] is True
    assert api.post(f"/kudos/tester/{TODAY}", email=OTHER).get_json() == {"count": 0, "mine": False}

    assert api.post(path).status_code == 404  # not your own
    assert api.post(path, email=STRANGER).status_code == 404
    assert api.post(f"/kudos/tester/{TODAY}/3", email=OTHER).status_code == 404
    assert api.post("/kudos/tester/not-a-date/0", email=OTHER).status_code == 404
    with api.app.app_context():
        social.set_visibility(USER, TODAY, social.PRIVATE)
        db.session.commit()
    assert api.post(path, email=OTHER).status_code == 404


def test_comments_add_and_delete(api):
    friends(api)
    stranger(api)
    save(api)
    path = f"/comments/tester/{TODAY}/0"
    r = api.post(path, email=OTHER, json={"body": "  Nice work!  "})
    (first,) = r.get_json()["comments"]
    assert r.status_code == 201 and first["body"] == "Nice work!"
    assert first["author"]["handle"] == "other" and first["can_delete"] is True
    mine = api.post(path, json={"body": "Thanks"}).get_json()  # on your own workout
    assert [c["body"] for c in mine["comments"]] == ["Nice work!", "Thanks"]
    assert all(c["can_delete"] for c in mine["comments"])  # the owner may remove any

    for body in ({"body": "   "}, {}):
        r = api.post(path, email=OTHER, json=body)
        assert r.status_code == 422 and r.get_json()["error"]["code"] == "empty_comment"
    assert api.post(path, email=OTHER, json={"body": 5}).status_code == 400
    assert api.post(path, email=STRANGER, json={"body": "hi"}).status_code == 404

    thanks = mine["comments"][1]["id"]
    assert delete(api, f"/comments/{thanks}", email=STRANGER).status_code == 404
    assert delete(api, f"/comments/{thanks}", email=OTHER).status_code == 404  # not theirs
    left = delete(api, f"/comments/{first['id']}", email=OTHER).get_json()
    assert [c["body"] for c in left["comments"]] == ["Thanks"]
    assert delete(api, f"/comments/{first['id']}", email=OTHER).status_code == 404


def test_a_former_friend_takes_a_comment_back_and_sees_no_others(api):
    friends(api)
    save(api)
    path = f"/comments/tester/{TODAY}/0"
    theirs = api.post(path, email=OTHER, json={"body": "Nice"}).get_json()["comments"][0]["id"]
    api.post(path, json={"body": "Thanks"})
    api.post("/friends/remove/other")
    r = delete(api, f"/comments/{theirs}", email=OTHER)
    assert r.status_code == 200 and r.get_json() == {"kudos": 0, "kudoed": False, "comments": []}


def test_friends_lists_activity_and_marks_it_seen(api):
    friends(api)
    save_with_secrets(api)
    api.post(f"/kudos/tester/{TODAY}/0", email=OTHER)
    api.post(f"/comments/tester/{TODAY}/0", email=OTHER, json={"body": "Nice work!"})
    assert api.get("/me").get_json()["unseen"] == 2

    activity = api.get("/friends").get_json()["activity"]
    assert sorted(e["kind"] for e in activity) == ["comment", "kudos"]
    comment = next(e for e in activity if e["kind"] == "comment")
    assert comment["who"]["handle"] == "other" and comment["body"] == "Nice work!"
    assert comment["date"] == TODAY and comment["session"] == 0 and comment["at"].endswith("Z")
    assert all(e["new"] for e in activity)

    assert api.get("/me").get_json()["unseen"] == 0
    assert not any(e["new"] for e in api.get("/friends").get_json()["activity"])


# --- Stage 5: routines, manual entry, the checklist, visibility ---------------------

PUSH = {
    "name": "  Push   day ",
    "blocks": [
        {"name": "Warm up", "body": "5 min row"},
        {"name": "", "body": ""},
        {"body": "Bench press 185 lbs, 3 sets of ___\r\nDips 3 sets of ___"},
    ],
}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/routines"),
        ("post", "/routines"),
        ("get", "/routines/1"),
        ("put", "/routines/1"),
        ("delete", "/routines/1"),
        ("get", "/log/manual"),
        ("post", "/onboarding/dismiss"),
        ("put", f"/day/{TODAY}/visibility"),
    ],
)
def test_stage_5_endpoints_need_a_token(client, method, path):
    r = getattr(client, method)(f"/api/v1{path}")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"


def test_routine_create_list_and_read(api):
    assert api.get("/routines").get_json() == {"routines": []}
    r = api.post("/routines", json=PUSH)
    made = r.get_json()
    assert r.status_code == 201 and made["name"] == "Push day"
    # The empty block is dropped, and the rest keep their order.
    assert made["blocks"] == [
        {"name": "Warm up", "body": "5 min row"},
        {"name": "", "body": "Bench press 185 lbs, 3 sets of ___\nDips 3 sets of ___"},
    ]
    assert api.get("/routines").get_json() == {
        "routines": [{"id": made["id"], "name": "Push day", "block_count": 2}]
    }
    assert api.get(f"/routines/{made['id']}").get_json() == made
    # The website lists the same routine.
    with api.client.session_transaction() as s:
        s["user_email"] = USER
    assert b"Push day" in api.client.get("/routines").data


def test_routine_edit_replaces_the_name_and_blocks(api):
    first = api.post("/routines", json=PUSH).get_json()["id"]
    second = api.post("/routines", json={"name": "Legs"}).get_json()
    assert second["blocks"] == []
    r = api.put(f"/routines/{first}", json={"name": "Push", "blocks": [{"body": "Bench"}]})
    assert r.status_code == 200
    assert r.get_json() == {"id": first, "name": "Push", "blocks": [{"name": "", "body": "Bench"}]}
    # The one just changed leads the list.
    assert [x["name"] for x in api.get("/routines").get_json()["routines"]] == ["Push", "Legs"]


@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"name": "   ", "blocks": [{"body": "Bench"}]}, 422, "bad_routine"),
        ({"blocks": [{"body": "Bench"}]}, 422, "bad_routine"),
        ({"name": 5}, 400, "bad_request"),
        ({"name": "Push", "blocks": "Bench"}, 400, "bad_request"),
        ({"name": "Push", "blocks": ["Bench"]}, 400, "bad_request"),
        ({"name": "Push", "blocks": [{"body": 5}]}, 400, "bad_request"),
    ],
)
def test_routine_refusals_save_nothing(api, body, status, code):
    made = api.post("/routines", json=PUSH).get_json()
    for r in (api.post("/routines", json=body), api.put(f"/routines/{made['id']}", json=body)):
        assert r.status_code == status and r.get_json()["error"]["code"] == code
    assert r.get_json()["error"]["message"]
    assert len(api.get("/routines").get_json()["routines"]) == 1
    assert api.get(f"/routines/{made['id']}").get_json() == made


def test_routine_blank_name_reuses_the_websites_message(api):
    r = api.post("/routines", json={"name": ""})
    assert r.get_json()["error"]["message"] == "Give the routine a name."


def test_routine_long_text_is_cut_to_size(api):
    body = {"name": "n" * 100, "blocks": [{"name": "b" * 100, "body": "x"}] * 30}
    made = api.post("/routines", json=body).get_json()
    assert len(made["name"]) == 60 and len(made["blocks"]) == 20
    assert len(made["blocks"][0]["name"]) == 40


def test_routines_are_only_ever_your_own(api):
    mine = api.post("/routines", json=PUSH).get_json()
    assert api.get("/routines", email=OTHER).get_json() == {"routines": []}
    for r in (
        api.get(f"/routines/{mine['id']}", email=OTHER),
        api.put(f"/routines/{mine['id']}", email=OTHER, json={"name": "Theirs"}),
        delete(api, f"/routines/{mine['id']}", email=OTHER),
    ):
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    assert api.get(f"/routines/{mine['id']}").get_json() == mine


def test_routine_delete(api):
    first = api.post("/routines", json=PUSH).get_json()["id"]
    second = api.post("/routines", json={"name": "Legs"}).get_json()["id"]
    r = delete(api, f"/routines/{first}")
    assert r.status_code == 200
    assert r.get_json() == {"routines": [{"id": second, "name": "Legs", "block_count": 0}]}
    assert api.get(f"/routines/{first}").status_code == 404
    assert delete(api, f"/routines/{first}").status_code == 404
    with api.app.app_context():
        assert RoutineBlock.query.count() == 0


def test_a_recording_from_a_routine_takes_its_name(api, fake_llm):
    fake_llm.queue(BENCH)
    text = "Warm up\n5 min row\n\nBench press 185 lbs, 3 sets of 5"
    heard = api.post(
        f"/parse?today={TODAY}", json={"text": text, "routine_name": " Push  day "}
    ).get_json()
    assert heard["title"] == "Push day" and heard["entries"][0]["exercise"] == "bench press"
    assert text in fake_llm.calls[-1][1]
    saved = save(api, title=heard["title"]).get_json()
    assert api.get(f"/day/{TODAY}?session={saved['session']}").get_json()["title"] == "Push day"


def test_manual_entry_names_and_save(api, fake_llm):
    names = api.get("/log/manual").get_json()
    assert "Barbell Bench Press" in names["exercises"] and names["activities"]
    assert all(isinstance(n, str) and n for n in names["exercises"] + names["activities"])
    # The form saves through POST /sessions, with no reading of text and no log spent.
    body = {
        "entries": [{"exercise": "Barbell Bench Press", "weight": "185", "sets": "3", "reps": "5"}],
        "cardio": [{"activity": names["activities"][0], "duration": "20"}],
        "bodyweight": "160",
    }
    assert save(api, **body).status_code == 201
    day = api.get(f"/day/{TODAY}").get_json()
    assert day["lifts"][0]["weight"] == "185 lbs" and day["bodyweight"] == "160 lbs"
    assert len(day["cardio"]) == 1
    assert api.get("/me").get_json()["quota"] == {"left": 2, "limit": 2}


def test_checklist_dismiss_hides_it_for_good(api):
    assert api.get(f"/home?today={TODAY}").get_json()["checklist"] is not None
    assert api.get(f"/home?today={TODAY}", email=OTHER).get_json()["checklist"] is not None
    for _ in range(2):  # hiding it twice is fine
        r = api.post("/onboarding/dismiss")
        assert r.status_code == 200 and r.get_json() == {"checklist": None}
    assert api.get(f"/home?today={TODAY}").get_json()["checklist"] is None
    save(api)
    assert api.get(f"/home?today={TODAY}").get_json()["checklist"] is None
    # Only yours.
    assert api.get(f"/home?today={TODAY}", email=OTHER).get_json()["checklist"] is not None


def test_day_visibility_hides_a_day_from_friends_and_shows_it_again(api):
    add_profile(api)
    add_profile(api, OTHER, "other")
    with api.app.app_context():
        social.befriend(USER, OTHER)
    save(api)
    feed = lambda: api.get(f"/feed?today={TODAY}", email=OTHER).get_json()["cards"]  # noqa: E731
    assert len(feed()) == 1

    r = api.put(f"/day/{TODAY}/visibility", json={"visibility": "private"})
    assert r.status_code == 200 and r.get_json() == {"date": TODAY, "visibility": "private"}
    assert api.get(f"/day/{TODAY}").get_json()["visibility"] == "private"
    assert feed() == []

    assert api.put(f"/day/{TODAY}/visibility", json={"visibility": "friends"}).status_code == 200
    assert api.get(f"/day/{TODAY}").get_json()["visibility"] == "friends"
    assert len(feed()) == 1


def test_day_visibility_refusals(api):
    save(api)
    for body in ({}, {"visibility": "public"}, {"visibility": 1}, {"visibility": ""}):
        r = api.put(f"/day/{TODAY}/visibility", json=body)
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"
    assert api.get(f"/day/{TODAY}").get_json()["visibility"] == "friends"
    # A day that isn't one, a day with nothing on it, and a day with only a weigh-in.
    save(api, date="2026-09-13", entries=[], bodyweight="160")
    for when in ("someday", "2026-09-01", "2026-09-13"):
        r = api.put(f"/day/{when}/visibility", json={"visibility": "private"})
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    with api.app.app_context():
        assert SessionVisibility.query.filter_by(visibility="private").count() == 0
    # Somebody else's day is not yours to set: it is simply not there.
    r = api.put(f"/day/{TODAY}/visibility", email=OTHER, json={"visibility": "private"})
    assert r.status_code == 404


# --- Stage 6: deleting an account -------------------------------------------------


def rows_naming(email):
    """{table: rows} for every table with an email column, counting those that hold
    `email` in any of them. A routine's blocks count as the routine owner's."""
    counts = {}
    for table in db.metadata.sorted_tables:
        columns = [c for c in table.columns if c.name.endswith("_email")]
        if columns:
            found = db.session.execute(select(table).where(or_(*(c == email for c in columns))))
            counts[table.name] = len(found.all())
    counts["routine_block"] = (
        RoutineBlock.query.join(routines.Routine, RoutineBlock.routine_id == routines.Routine.id)
        .filter(routines.Routine.user_email == email)
        .count()
    )
    return counts


def fill_account(api, fake_llm):
    """USER and OTHER, friends, each with something in every table that names an
    email, and something of theirs on the other's workout."""
    for email, handle in ((USER, "tester"), (OTHER, "other")):
        fake_llm.queue(BENCH)
        assert (
            api.post(f"/parse?today={TODAY}", email=email, json={"text": "bench"}).status_code
            == 200
        )
        r = save(
            api,
            email=email,
            title="Push day",
            bodyweight="180",
            cardio=[{"activity": "run", "distance": "3 miles", "duration": "", "notes": "slow"}],
        )
        assert r.status_code == 201
        assert api.put("/preferences", email=email, json={"weight_unit": "kg"}).status_code == 200
        assert api.post("/routines", email=email, json=PUSH).status_code == 201
        with api.app.app_context():
            social.save_profile(email, handle, handle.title())
            rest.add_rule(email, "weekdays", weekdays=(6,), anchor=date(2026, 9, 14))
            rest.set_day(email, date(2026, 9, 12), date(2026, 9, 14), wanted=True)
            db.session.add(SessionMeta(owner_email=email, date=TODAY, title="Old title"))
            db.session.commit()
    with api.app.app_context():
        social.befriend(USER, OTHER)
        for giver, owner in ((USER, OTHER), (OTHER, USER)):
            social.toggle_kudos(giver, owner, TODAY)
            assert social.add_comment(giver, owner, TODAY, "Nice work!") is not None


def later(monkeypatch, seconds=5):
    """Move every clock forward: a sign-in in the very second an account was deleted
    is cut off with the rest."""
    now = time.time() + seconds
    monkeypatch.setattr(time, "time", lambda: now)


def test_account_delete_needs_a_token(client):
    r = client.delete("/api/v1/account")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"


def test_account_delete_removes_every_row_that_names_the_email(api, fake_llm):
    fill_account(api, fake_llm)
    with api.app.app_context():
        before, others = rows_naming(USER), rows_naming(OTHER)
        # Nothing to delete would prove nothing: a new table with an email column has
        # to be filled in fill_account, and emptied in account.delete.
        empty = sorted(t for t, n in before.items() if n == 0 and t != "account_cutoff")
        assert empty == []

    r = api.call("delete", "/account")
    assert r.status_code == 200 and r.get_json() == {"deleted": True}

    with api.app.app_context():
        assert {t: n for t, n in rows_naming(USER).items() if n} == {}
        # The other person keeps everything that is theirs alone.
        left = rows_naming(OTHER)
        shared = {"friendship", "session_kudos", "comment"}
        assert {t: n for t, n in left.items() if t not in shared} == {
            t: n for t, n in others.items() if t not in shared
        }
        assert all(left[t] == 0 for t in shared)
    feed = api.get(f"/feed?today={TODAY}", email=OTHER).get_json()
    assert feed["cards"] == []
    theirs = api.get(f"/day/{TODAY}", email=OTHER).get_json()
    assert theirs["reactions"]["kudos"] == 0 and theirs["reactions"]["comments"] == []


def test_account_delete_clears_the_table_session_kudos_replaced(api):
    """migrate.py copies `kudos` into session_kudos at every start."""
    with api.app.app_context():
        db.session.execute(
            text(
                "CREATE TABLE kudos (id INTEGER PRIMARY KEY, owner_email VARCHAR, date VARCHAR, "
                "giver_email VARCHAR, created_at DATETIME)"
            )
        )
        for owner, giver in ((USER, OTHER), (OTHER, USER), (OTHER, "third@example.com")):
            db.session.execute(
                text(
                    "INSERT INTO kudos (owner_email, date, giver_email, created_at) "
                    "VALUES (:owner, :date, :giver, '2026-09-14 10:00:00')"
                ),
                {"owner": owner, "date": TODAY, "giver": giver},
            )
        db.session.commit()
        migrate.run()
        assert rows_naming(USER)["session_kudos"] == 2

    assert api.call("delete", "/account").status_code == 200
    with api.app.app_context():
        migrate.run()
        assert rows_naming(USER)["session_kudos"] == 0
        assert db.session.execute(text("SELECT COUNT(*) FROM kudos")).scalar() == 1
        db.session.execute(text("DROP TABLE kudos"))
        db.session.commit()


def test_account_delete_stops_every_token_for_the_email(api, monkeypatch):
    mine, another, theirs = bearer(api.app), bearer(api.app), bearer(api.app, OTHER)
    assert api.get("/me", headers=another).status_code == 200
    assert api.call("delete", "/account", headers=mine).status_code == 200

    for headers in (mine, another):
        r = api.get("/me", headers=headers)
        assert r.status_code == 401 and r.get_json()["error"]["code"] == "invalid_token"
        assert save(api, headers=headers).status_code == 401
    assert api.get("/me", headers=theirs).status_code == 200
    with api.app.app_context():
        assert Workout.query.count() == 0
        assert rows_naming(USER)["user_activity"] == 0  # a dead token leaves no trace

    # Signing in again afterwards is a new, empty account.
    later(monkeypatch)
    me = api.get("/me")
    assert me.status_code == 200 and me.get_json()["profile"] is None
    assert save(api).status_code == 201


def test_account_cutoff_holds_no_email_and_is_dropped_when_no_longer_needed(api, monkeypatch):
    assert api.call("delete", "/account").status_code == 200
    with api.app.app_context():
        (cutoff,) = AccountCutoff.query.all()
        assert USER not in cutoff.email_hash and len(cutoff.email_hash) == 64
        assert account.revoked(USER, cutoff.not_before)
        assert not account.revoked(USER, cutoff.not_before + 1)
        assert not account.revoked(OTHER, 0)

    # Once the tokens it refuses have all expired, the next deletion sweeps it away.
    later(monkeypatch, account.CUTOFF_KEPT + 60)
    assert account.CUTOFF_KEPT >= auth.API_TOKEN_MAX_AGE
    assert api.call("delete", "/account", email=OTHER).status_code == 200
    with api.app.app_context():
        assert AccountCutoff.query.count() == 1 and not account.revoked(USER, 0)


def test_website_account_delete(api, fake_llm):
    fill_account(api, fake_llm)
    token = bearer(api.app)
    here, elsewhere = api.app.test_client(), api.app.test_client()
    for browser in (here, elsewhere):
        with browser.session_transaction() as s:
            s["user_email"] = USER
            s["llm"] = {"provider": "site", "model": "", "api_key": "", "base_url": ""}
    page = here.get("/settings").data.decode()
    assert 'action="/account/delete"' in page and "Delete account" in page
    assert here.get("/account/delete").status_code == 405

    r = here.post("/account/delete")
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")
    with here.session_transaction() as s:
        assert "user_email" not in s and "llm" not in s
    assert "has been deleted" in here.get("/welcome").data.decode()
    with api.app.app_context():
        assert {t: n for t, n in rows_naming(USER).items() if n} == {}

    # Signed out everywhere: the app's token, and a browser that was signed in too.
    assert api.get("/me", headers=token).status_code == 401
    r = elsewhere.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")
    with elsewhere.session_transaction() as s:
        assert "user_email" not in s
    with api.app.app_context():
        assert {t: n for t, n in rows_naming(USER).items() if n} == {}


def test_website_account_delete_needs_a_sign_in_and_a_csrf_token(client):
    r = client.post("/account/delete")
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")

    app = create_app({**base_test_config(), "WTF_CSRF_ENABLED": True})
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = USER
    with app.app_context():
        db.session.add(Workout(user_email=USER, date=TODAY, exercise="squat"))
        db.session.commit()
    assert client.post("/account/delete").status_code == 400
    with app.app_context():
        assert Workout.query.count() == 1 and AccountCutoff.query.count() == 0
        db.session.remove()
        db.drop_all()


def test_account_delete_in_the_app_signs_the_website_out(api, monkeypatch):
    browser = api.app.test_client()
    with browser.session_transaction() as s:
        s["user_email"] = USER
        s[auth.SESSION_SINCE] = int(time.time())
    assert api.call("delete", "/account").status_code == 200
    assert browser.get("/").headers["Location"].endswith("/welcome")

    # A sign-in on the website after the deletion stands.
    later(monkeypatch)
    with browser.session_transaction() as s:
        s["user_email"] = USER
        s[auth.SESSION_SINCE] = int(time.time())
        s["llm"] = {"provider": "site", "model": "", "api_key": "", "base_url": ""}
    assert browser.get("/").status_code == 200
