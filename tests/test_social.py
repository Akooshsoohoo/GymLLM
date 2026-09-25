"""Profiles, friendships, privacy, feed, kudos and comments."""

import pytest

from gymllm import social
from gymllm.extensions import db
from gymllm.models import BodyWeight, Cardio, Comment, Friendship, Kudos

from .conftest import OTHER, USER

THIRD = "third@example.com"


@pytest.fixture
def third_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = THIRD
    return client


@pytest.fixture
def pair(add_profile):
    """USER (@tester) and OTHER (@sam) both have profiles; not yet friends."""
    add_profile(USER, "tester", display_name="Tess")
    add_profile(OTHER, "sam", display_name="Sam")


def _add(app, model, **kwargs):
    with app.app_context():
        db.session.add(model(**kwargs))
        db.session.commit()


# --- Profiles -------------------------------------------------------------------


@pytest.mark.parametrize(
    "handle, ok",
    [("sam", True), ("sam_99", True), ("ab", False), ("a" * 21, False), ("sam!", False),
     ("Sam", False), ("settings", False)],
)  # fmt: skip
def test_handle_rules(app, handle, ok):
    with app.app_context():
        assert (social.handle_error(handle, USER) is None) is ok


def test_social_pages_send_you_to_profile_setup_first(logged_in):
    r = logged_in.get("/friends")
    assert r.status_code == 302
    assert "/profile/edit?next=/friends" in r.headers["Location"]


def test_logging_does_not_need_a_profile(logged_in):
    assert logged_in.get("/").status_code == 200


def test_create_profile_lowercases_handle_and_rejects_taken(app, logged_in, other_client):
    r = logged_in.post("/profile/edit", data={"handle": "@Lifter", "display_name": "Tess"})
    assert r.status_code == 302
    with app.app_context():
        assert social.get_profile(USER).handle == "lifter"
    r = other_client.post("/profile/edit", data={"handle": "LIFTER", "display_name": "Sam"})
    assert r.status_code == 400
    assert b"taken" in r.data


def test_profile_setup_returns_to_next(logged_in):
    r = logged_in.post(
        "/profile/edit", data={"handle": "tess", "display_name": "Tess", "next": "/feed"}
    )
    assert r.headers["Location"].endswith("/feed")
    r = logged_in.post(
        "/profile/edit",
        data={"handle": "tess", "display_name": "Tess", "next": "https://evil.example/"},
    )
    assert "evil" not in r.headers["Location"]


def test_nav_shows_handle_once_profile_exists(logged_in, add_profile):
    add_profile(USER, "tester")
    assert b"@tester" in logged_in.get("/settings").data


# --- Friendships ----------------------------------------------------------------


def test_request_then_accept(app, pair, logged_in, other_client):
    logged_in.post("/friends/request/sam")
    with app.app_context():
        assert social.relationship(USER, OTHER) == social.OUTGOING
        assert social.relationship(OTHER, USER) == social.INCOMING
        assert social.unseen_count(OTHER) == 1
    other_client.post("/friends/accept/tester")
    with app.app_context():
        assert social.relationship(USER, OTHER) == social.FRIENDS


def test_crossed_requests_become_friends(app, pair, logged_in, other_client):
    logged_in.post("/friends/request/sam")
    other_client.post("/friends/request/tester")
    with app.app_context():
        assert social.relationship(USER, OTHER) == social.FRIENDS
        assert Friendship.query.count() == 1


def test_cannot_accept_your_own_request(app, pair, logged_in):
    logged_in.post("/friends/request/sam")
    logged_in.post("/friends/accept/sam")
    with app.app_context():
        assert social.relationship(USER, OTHER) == social.OUTGOING


def test_unfriend_forgets_the_pair(app, pair, make_friends, logged_in):
    make_friends()
    logged_in.post("/friends/remove/sam")
    with app.app_context():
        assert social.relationship(USER, OTHER) == social.NONE


def test_search_by_handle_prefix(pair, logged_in):
    page = logged_in.get("/friends?q=@sa").data
    assert b"@sam" in page
    assert b"Add friend" in page


def test_invite_link_makes_friends(app, add_profile, logged_in, other_client):
    code = add_profile(USER, "tester")
    add_profile(OTHER, "sam")
    assert b"Add Tester" in other_client.get(f"/invite/{code}").data
    other_client.post(f"/invite/{code}")
    with app.app_context():
        assert social.relationship(USER, OTHER) == social.FRIENDS


def test_invite_link_survives_login(app, add_profile, client):
    code = add_profile(USER, "tester")
    r = client.get(f"/invite/{code}")
    assert b"Sign in with Google" in r.data
    with client.session_transaction() as s:
        assert s["after_login"] == f"/invite/{code}"
        s["user_email"] = OTHER
    r = client.get("/oauth_success")
    assert r.headers["Location"].endswith(f"/invite/{code}")
    # No profile yet: set one up, then come back to the invite.
    r = client.get(f"/invite/{code}")
    assert "/profile/edit" in r.headers["Location"]


def test_own_invite_link_is_a_no_op(app, add_profile, logged_in):
    code = add_profile(USER, "tester")
    r = logged_in.post(f"/invite/{code}")
    assert r.headers["Location"].endswith("/u/tester")
    with app.app_context():
        assert Friendship.query.count() == 0


def test_new_invite_link_retires_the_old(app, add_profile, logged_in, other_client):
    old = add_profile(USER, "tester")
    logged_in.post("/profile/invite-reset")
    assert other_client.get(f"/invite/{old}").status_code == 404


# --- Privacy --------------------------------------------------------------------


def test_stranger_sees_only_the_header(pair, add_workout, other_client):
    add_workout(notes="felt heavy")
    page = other_client.get("/u/tester").data
    assert b"Tess" in page
    assert b"barbell bench press" not in page
    assert b"Add friend" in page


def test_friend_sees_lifts_but_not_notes_or_bodyweight(
    app, pair, make_friends, add_workout, other_client
):
    make_friends()
    add_workout(date="2026-01-10", notes="secret note")
    _add(app, BodyWeight, user_email=USER, date="2026-01-10", weight="181 lbs")
    page = other_client.get("/u/tester").data
    assert b"barbell bench press" in page
    assert b"secret note" not in page
    assert b"181 lbs" not in page
    with app.app_context():
        rows, cardio, weights = social.visible_data(OTHER, USER)
        assert rows[0]["notes"] == ""
        assert weights == []


def test_bodyweight_visible_when_shared(app, add_profile, make_friends, add_workout):
    add_profile(USER, "tester", share_bodyweight=True)
    add_profile(OTHER, "sam")
    make_friends()
    _add(app, BodyWeight, user_email=USER, date="2026-01-10", weight="181 lbs")
    with app.app_context():
        assert social.visible_data(OTHER, USER)[2][0]["weight"] == "181 lbs"


def test_you_see_your_own_notes(app, pair, add_workout):
    add_workout(notes="mine")
    with app.app_context():
        assert social.visible_data(USER, USER)[0][0]["notes"] == "mine"


def test_strangers_get_404_on_compare_kudos_and_comments(pair, add_workout, other_client):
    add_workout(date="2026-01-10")
    assert other_client.get("/u/tester/compare").status_code == 404
    assert other_client.post("/kudos/tester/2026-01-10").status_code == 404
    assert other_client.post("/comments/tester/2026-01-10", data={"body": "hi"}).status_code == 404


def test_unknown_handle_is_404(pair, logged_in):
    assert logged_in.get("/u/nobody").status_code == 404


# --- Feed, kudos, comments ------------------------------------------------------


def test_feed_shows_friends_sessions_newest_first(app, pair, make_friends, add_workout, logged_in):
    make_friends()
    add_workout(user_email=OTHER, date="2026-01-05", exercise="squat", weight="200 lbs")
    add_workout(user_email=OTHER, date="2026-01-12", exercise="squat", weight="225 lbs")
    _add(app, Cardio, user_email=OTHER, date="2026-01-08", activity="running", distance="5 km")
    page = logged_in.get("/feed").data.decode()
    assert page.index("12 Jan") < page.index("8 Jan") < page.index("5 Jan")
    assert "running" in page
    assert "PR</span>" in page  # 225 beat 200


def test_feed_skips_weigh_in_only_days(app, add_profile, make_friends, logged_in):
    add_profile(USER, "tester")
    add_profile(OTHER, "sam", share_bodyweight=True)
    make_friends()
    _add(app, BodyWeight, user_email=OTHER, date="2026-01-10", weight="150 lbs")
    with app.app_context():
        assert social.feed(USER)[0] == []


def test_feed_pages_by_date_without_splitting_one(app, pair, make_friends, add_workout):
    make_friends()
    for day in range(1, 6):
        add_workout(user_email=OTHER, date=f"2026-01-0{day}")
    with app.app_context():
        page, nxt = social.feed(USER, limit=2)
        assert [c["date"] for c in page] == ["2026-01-05", "2026-01-04"]
        page, nxt = social.feed(USER, before=nxt, limit=2)
        assert [c["date"] for c in page] == ["2026-01-03", "2026-01-02"]
        page, nxt = social.feed(USER, before=nxt, limit=2)
        assert [c["date"] for c in page] == ["2026-01-01"]
        assert nxt is None


def test_home_shows_friends_activity(pair, make_friends, add_workout, logged_in):
    make_friends()
    add_workout(user_email=OTHER, exercise="deadlift")
    page = logged_in.get("/").data
    assert b"deadlift" in page
    assert b"See all" in page


def test_kudos_toggle(app, pair, make_friends, add_workout, logged_in):
    make_friends()
    add_workout(user_email=OTHER, date="2026-01-10")
    headers = {"Accept": "application/json"}
    assert logged_in.post("/kudos/sam/2026-01-10", headers=headers).json == {
        "count": 1,
        "mine": True,
    }
    assert logged_in.post("/kudos/sam/2026-01-10", headers=headers).json == {
        "count": 0,
        "mine": False,
    }
    r = logged_in.post("/kudos/sam/2026-01-10")
    assert r.headers["Location"].endswith("#s-sam-2026-01-10")
    with app.app_context():
        assert Kudos.query.count() == 1


def test_no_kudos_for_your_own_session(pair, add_workout, logged_in):
    add_workout(date="2026-01-10")
    assert logged_in.post("/kudos/tester/2026-01-10").status_code == 404


def test_kudos_need_a_logged_session(pair, make_friends, logged_in):
    make_friends()
    assert logged_in.post("/kudos/sam/2026-01-10").status_code == 404


def test_comment_and_delete_permissions(
    app, pair, make_friends, add_workout, add_profile, logged_in, other_client, third_client
):
    add_profile(THIRD, "third")
    make_friends()
    make_friends(THIRD, OTHER)
    add_workout(user_email=OTHER, date="2026-01-10")
    logged_in.post("/comments/sam/2026-01-10", data={"body": "  strong <b>work</b>  "})
    with app.app_context():
        c = Comment.query.one()
        assert c.body == "strong <b>work</b>"
        cid = c.id
    page = other_client.get("/u/sam").data
    assert b"strong &lt;b&gt;work&lt;/b&gt;" in page
    # A friend of the owner who didn't write it can't delete it.
    assert third_client.post(f"/comments/{cid}/delete").status_code == 404
    # The session's owner can.
    other_client.post(f"/comments/{cid}/delete")
    with app.app_context():
        assert Comment.query.count() == 0


def test_empty_comment_is_ignored(app, pair, make_friends, add_workout, logged_in):
    make_friends()
    add_workout(user_email=OTHER, date="2026-01-10")
    logged_in.post("/comments/sam/2026-01-10", data={"body": "   "})
    with app.app_context():
        assert Comment.query.count() == 0


def test_you_can_reply_on_your_own_day_page(app, pair, add_workout, logged_in):
    add_workout(date="2026-01-10")
    page = logged_in.get("/day/2026-01-10").data
    assert b'id="social"' in page
    logged_in.post("/comments/tester/2026-01-10", data={"body": "thanks!"})
    assert b"thanks!" in logged_in.get("/day/2026-01-10").data


def test_activity_badge_clears_on_friends_page(
    app, pair, make_friends, add_workout, logged_in, other_client
):
    make_friends()
    add_workout(date="2026-01-10")
    other_client.post("/kudos/tester/2026-01-10")
    with app.app_context():
        assert social.unseen_count(USER) == 1
    page = logged_in.get("/friends").data
    assert b"gave kudos to" in page
    with app.app_context():
        assert social.unseen_count(USER) == 0


def test_compare_page_renders_for_friends(pair, make_friends, add_workout, logged_in):
    make_friends()
    add_workout(date="2026-09-01", exercise="bench press", weight="185 lbs")
    add_workout(user_email=OTHER, date="2026-09-02", exercise="bench press", weight="200 lbs")
    page = logged_in.get("/u/sam/compare?range=all&today=2026-09-10").data
    assert b"Lifts you both do" in page
    assert b"bench press" in page
    assert b"15 lbs" in page
