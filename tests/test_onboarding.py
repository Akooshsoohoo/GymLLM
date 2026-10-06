"""The first-use experience: Home's first-run log box and getting-started checklist,
the review screen's first-time and dead-end states, and the invite path."""

from sqlalchemy import text

from gymllm import migrate, preferences, quota
from gymllm.extensions import db
from gymllm.llm.client import AuthError, RateLimitError

from .conftest import OTHER, USER

PARSED = {
    "date": "2026-09-13",
    "exercises": [
        {"exercise": "barbell bench press", "weight": "135 lbs", "sets": 3, "reps": [8, 8, 8]}
    ],
}
DONE = '<span class="sr-only"> (done)</span>'


def _save(client, day="2026-09-13"):
    r = client.post(
        "/confirm",
        data={"date": day, "num_entries": "1", "entry-0-exercise": "barbell bench press"},
    )
    return client.get(r.headers["Location"]).data.decode()


# --- Home -----------------------------------------------------------------------


def test_new_user_home_leads_with_the_log_box(logged_in):
    body = logged_in.get("/").data.decode()
    assert 'class="home-log is-first"' in body and "Log your first workout" in body
    assert "Getting started" in body and DONE not in body
    # The checklist stands in for the profile prompt.
    assert "Set up a profile to see friends" not in body


def test_returning_user_sees_no_first_run_card(logged_in, add_workout):
    add_workout()
    body = logged_in.get("/").data.decode()
    assert "is-first" not in body and "Log your first workout" not in body
    assert "What did you get up to" in body
    assert "Log a workout" + DONE in body and "Set up your profile" + DONE not in body


def test_checklist_ticks_off_and_goes_when_done(logged_in, add_workout, add_profile, make_friends):
    add_workout()
    add_profile(USER, "tester")
    add_profile(OTHER, "sam")
    body = logged_in.get("/").data.decode()
    assert "Set up your profile" + DONE in body and "Add a friend" + DONE not in body
    make_friends()
    assert "Getting started" not in logged_in.get("/").data.decode()


def test_checklist_can_be_hidden_for_good(app, logged_in):
    r = logged_in.post("/onboarding/dismiss")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    body = logged_in.get("/").data.decode()
    assert "Getting started" not in body and "Set up a profile to see friends" in body
    with app.app_context():
        assert preferences.onboarding_dismissed(USER)
        assert not preferences.onboarding_dismissed(OTHER)


def test_hiding_the_checklist_keeps_the_weight_unit(app, logged_in):
    with app.app_context():
        preferences.set_weight_unit(USER, "kg")
    logged_in.post("/onboarding/dismiss")
    with app.app_context():
        assert preferences.get_weight_unit(USER) == "kg"


def test_only_the_first_save_is_marked_as_a_first(logged_in):
    body = _save(logged_in)
    assert "First workout logged" in body and "see your progress" in body
    body = _save(logged_in, "2026-09-14")
    assert "First workout logged" not in body and '<span class="latest-badge">Saved</span>' in body


def test_log_box_carries_the_tips_everywhere(logged_in):
    for path in ("/", "/log"):
        body = logged_in.get(path).data.decode()
        assert 'data-dialog-open="tips"' in body and body.count('id="tips"') == 1


def test_tab_bar_names_the_record_button(logged_in):
    assert b"data-record-label>Record</span>" in logged_in.get("/").data


# --- Review ---------------------------------------------------------------------


def test_review_hint_only_before_the_first_save(logged_in, fake_llm, add_workout):
    fake_llm.queue(PARSED, PARSED)
    assert b"Tap anything to fix it" in logged_in.post("/review", data={"workout": "bench"}).data
    add_workout()
    assert b"Tap anything to fix it" not in logged_in.post("/review", data={"workout": "b"}).data


def test_review_is_private_until_there_is_a_profile(logged_in, fake_llm, add_profile):
    fake_llm.queue(PARSED, PARSED)
    r = logged_in.post("/review", data={"workout": "bench"})
    assert b'value="private" checked' in r.data
    add_profile(USER, "tester")
    r = logged_in.post("/review", data={"workout": "bench"})
    assert b'value="friends" checked' in r.data


def test_empty_parse_gets_tips_and_a_way_out(logged_in, fake_llm):
    r = logged_in.post("/review", data={"workout": "asdf"})  # the fake finds nothing
    body = r.data.decode()
    assert "find a workout in that" in body and "Here&#39;s what we heard" not in body
    assert "Shorthand works" in body and 'href="/log/manual"' in body
    assert "words-card reparse-form is-open" in body


def test_site_errors_give_the_free_log_back(site_user, site_app, fake_llm):
    for error in (RateLimitError("busy"), AuthError("bad key"), RuntimeError("boom")):
        fake_llm.error = error
        assert site_user.post("/review", data={"workout": "bench"}).status_code == 200
        with site_app.app_context():
            assert quota.remaining(USER, 2) == 2


def test_site_empty_parse_still_counts(site_user, site_app, fake_llm):
    site_user.post("/review", data={"workout": "asdf"})
    with site_app.app_context():
        assert quota.remaining(USER, 2) == 1


def test_site_limit_page_offers_manual_entry_not_a_retry(site_user, fake_llm):
    fake_llm.queue(PARSED, PARSED)
    for _ in range(2):
        site_user.post("/review", data={"workout": "bench"})
    body = site_user.post("/review", data={"workout": "bench"}).data.decode()
    assert "That&#39;s today&#39;s free logs." in body and "try that again" not in body
    assert "Change and try again" not in body
    assert 'href="/log/manual" class="btn btn-primary btn-sm">Add manually' in body


def test_refund_never_goes_below_zero(site_app):
    with site_app.app_context():
        quota.refund(USER)
        assert quota.used(USER) == 0
        quota.consume(USER, 2)
        quota.refund(USER)
        quota.refund(USER)
        assert quota.used(USER) == 0


# --- Invite ---------------------------------------------------------------------


def test_invite_keeps_the_inviter_through_profile_setup(add_profile, other_client):
    code = add_profile(USER, "tester", display_name="Tess")
    r = other_client.get(f"/invite/{code}")
    assert f"invite={code}" in r.headers["Location"]
    r = other_client.get(r.headers["Location"])
    assert b"Tess invited you" in r.data and f'name="invite" value="{code}"'.encode() in r.data
    r = other_client.post(
        "/profile/edit",
        data={"handle": "sam", "display_name": "Sam", "next": f"/invite/{code}", "invite": code},
        follow_redirects=True,
    )
    assert r.request.path == f"/invite/{code}"
    assert b"Profile created." in r.data and b"Find friends below" not in r.data
    assert b"Add Tess" in r.data


def test_plain_profile_setup_names_no_inviter(logged_in):
    r = logged_in.get("/profile/edit?invite=nope")
    assert r.status_code == 200 and b"invited you" not in r.data
    r = logged_in.post(
        "/profile/edit", data={"handle": "tess", "display_name": "Tess"}, follow_redirects=True
    )
    assert b"Profile created. Find friends below." in r.data


# --- Migration ------------------------------------------------------------------


def test_migration_adds_the_dismissed_flag_to_an_old_table(app):
    with app.app_context():
        with db.engine.begin() as conn:
            conn.execute(text("DROP TABLE user_preference"))
            conn.execute(
                text(
                    "CREATE TABLE user_preference "
                    "(user_email VARCHAR PRIMARY KEY, weight_unit VARCHAR NOT NULL)"
                )
            )
            conn.execute(text("INSERT INTO user_preference VALUES (:e, 'kg')"), {"e": USER})
        migrate.run()
        migrate.run()  # harmless twice
        assert preferences.onboarding_dismissed(USER) is False
        assert preferences.get_weight_unit(USER) == "kg"
        preferences.dismiss_onboarding(USER)
        assert preferences.onboarding_dismissed(USER) is True
