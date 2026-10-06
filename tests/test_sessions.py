"""Several workouts on one day: each save is its own named session, with its own
card, kudos and comments."""

import pytest
from sqlalchemy import create_engine, inspect, text

from gymllm import migrate, session_meta
from gymllm.extensions import db
from gymllm.models import Cardio, Comment, Kudos, Workout
from tests.conftest import OTHER, USER

DAY = "2026-03-10"


@pytest.fixture
def pair(add_profile):
    add_profile(USER, "tester", display_name="Tess")
    add_profile(OTHER, "sam", display_name="Sam")


def _confirm(client, exercise, title="", when=DAY, **extra):
    data = {
        "date": when,
        "title": title,
        "num_entries": "1",
        "entry-0-exercise": exercise,
        "entry-0-weight": "100 lbs",
        "entry-0-sets": "3",
        "entry-0-reps": "8, 8, 8",
        "entry-0-notes": "",
        **extra,
    }
    return client.post("/confirm", data=data)


def test_each_save_is_its_own_named_session(app, logged_in):
    first = _confirm(logged_in, "barbell back squat", "Leg day")
    second = _confirm(logged_in, "barbell bench press", "Evening push")
    assert first.headers["Location"] == f"/?saved={DAY}&session=0#my-latest"
    assert second.headers["Location"] == f"/?saved={DAY}&session=1#my-latest"
    with app.app_context():
        assert {(w.exercise, w.session) for w in Workout.query.all()} == {
            ("barbell back squat", 0),
            ("barbell bench press", 1),
        }
        assert session_meta.get(USER, DAY, 0).title == "Leg day"
        assert session_meta.get(USER, DAY, 1).title == "Evening push"


def test_home_shows_the_session_you_just_saved(logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day")
    _confirm(logged_in, "barbell bench press", "Evening push")
    body = logged_in.get(f"/?saved={DAY}&session=1").data.decode()
    card = body.split('id="my-latest"')[1].split("</article>")[0]
    assert (
        "Evening push" in card
        and "Barbell bench press" in card
        and "Barbell back squat" not in card
    )
    card = logged_in.get(f"/?saved={DAY}&session=0").data.decode().split('id="my-latest"')[1]
    assert "Leg day" in card.split("</article>")[0]


def test_untitled_sessions_get_numbered_default_names(logged_in):
    _confirm(logged_in, "barbell back squat")
    _confirm(logged_in, "barbell bench press")
    body = logged_in.get("/search").data.decode()
    assert "Tuesday workout" in body and "Tuesday workout 2" in body
    assert 'href="/day/2026-03-10?s=1"' in body


def test_sessions_list_has_a_card_per_session(logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day")
    _confirm(logged_in, "barbell bench press", "Evening push")
    body = logged_in.get("/search").data.decode()
    assert body.count('class="session-tile"') == 2


def test_day_page_shows_one_session_and_a_switcher(logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day")
    _confirm(logged_in, "barbell bench press", "Evening push")
    first = logged_in.get(f"/day/{DAY}").data.decode()
    second = logged_in.get(f"/day/{DAY}?s=1").data.decode()
    assert "day-sessions" in first and "Evening push" in first
    assert (
        "Barbell back squat" in first
        and "Barbell bench press" not in first.split("poster-rows")[1].split("</ul>")[0]
    )
    assert "Barbell bench press" in second.split("poster-rows")[1].split("</ul>")[0]


def test_weigh_in_rides_on_the_first_session_only(logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day", bodyweight="150 lbs")
    _confirm(logged_in, "barbell bench press", "Evening push")
    assert "150 lbs" in logged_in.get(f"/day/{DAY}").data.decode()
    assert "150 lbs" not in logged_in.get(f"/day/{DAY}?s=1").data.decode()
    assert 'name="bodyweight"' in logged_in.get(f"/day/{DAY}/edit").data.decode()
    assert 'name="bodyweight"' not in logged_in.get(f"/day/{DAY}/edit?s=1").data.decode()


def test_kudos_and_comments_belong_to_one_session(app, pair, make_friends, add_workout, logged_in):
    make_friends()
    add_workout(user_email=OTHER, date=DAY, session=0)
    add_workout(user_email=OTHER, date=DAY, session=1, exercise="deadlift")
    headers = {"Accept": "application/json"}
    assert logged_in.post(f"/kudos/sam/{DAY}/1", headers=headers).json == {
        "count": 1,
        "mine": True,
    }
    r = logged_in.post(f"/comments/sam/{DAY}/1", data={"body": "nice pull"})
    assert r.headers["Location"].endswith(f"#s-sam-{DAY}-1")
    with app.app_context():
        assert [(k.date, k.session) for k in Kudos.query.all()] == [(DAY, 1)]
        assert [(c.session, c.body) for c in Comment.query.all()] == [(1, "nice pull")]
    # the day's first session has none of it, and can be reacted to separately
    assert logged_in.post(f"/kudos/sam/{DAY}", headers=headers).json["count"] == 1
    body = logged_in.get("/feed").data.decode()
    assert f'id="s-sam-{DAY}-0"' in body and f'id="s-sam-{DAY}-1"' in body
    assert body.count("nice pull") >= 1
    assert logged_in.post(f"/kudos/sam/{DAY}/2").status_code == 404  # no such session


def test_edit_one_session_leaves_the_other_alone(app, logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day", bodyweight="150 lbs")
    _confirm(logged_in, "barbell bench press", "Evening push")
    r = logged_in.post(
        f"/day/{DAY}/edit?s=1",
        data={"date": DAY, "title": "Late push", "visibility": "friends", "num_entries": "0"},
    )
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/day/{DAY}?s=1")
    with app.app_context():
        assert session_meta.get(USER, DAY, 1).title == "Late push"
        assert session_meta.get(USER, DAY, 0).title == "Leg day"
        assert Workout.query.count() == 2


def test_moving_a_session_renumbers_it_and_takes_its_reactions(app, logged_in, pair):
    _confirm(logged_in, "barbell back squat", "Leg day")
    _confirm(logged_in, "barbell bench press", "Evening push")
    _confirm(logged_in, "row", "Pull", when="2026-03-11")
    with app.app_context():
        db.session.add(Kudos(owner_email=USER, date=DAY, session=1, giver_email=OTHER))
        db.session.commit()
    lift = next(w for w in _rows(app) if w["exercise"] == "barbell bench press")
    logged_in.post(
        f"/day/{DAY}/edit?s=1",
        data={
            "date": "2026-03-11",
            "title": "Evening push",
            "visibility": "friends",
            "num_entries": "0",
            f"lift-{lift['id']}-exercise": "barbell bench press",
        },
    )
    with app.app_context():
        moved = Workout.query.filter_by(exercise="barbell bench press").one()
        assert (moved.date, moved.session) == ("2026-03-11", 1)
        assert session_meta.get(USER, DAY, 1) is None
        assert session_meta.get(USER, "2026-03-11", 1).title == "Evening push"
        assert [(k.date, k.session) for k in Kudos.query.all()] == [("2026-03-11", 1)]


def _rows(app):
    with app.app_context():
        return [w.as_dict() for w in Workout.query.all()]


def test_removing_a_session_clears_its_title_and_reactions(app, logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day")
    _confirm(logged_in, "barbell bench press", "Evening push")
    with app.app_context():
        db.session.add(Comment(owner_email=USER, date=DAY, session=1, author_email=OTHER, body="x"))
        db.session.commit()
        lift = Workout.query.filter_by(exercise="barbell bench press").one().id
    logged_in.post(
        f"/day/{DAY}/edit?s=1",
        data={"date": DAY, "title": "", "num_entries": "0", f"lift-{lift}-delete": "1"},
    )
    with app.app_context():
        assert session_meta.get(USER, DAY, 1) is None
        assert Comment.query.count() == 0
        assert Workout.query.count() == 1
        assert session_meta.get(USER, DAY, 0).title == "Leg day"


def test_a_session_can_be_cardio_only(app, logged_in):
    _confirm(logged_in, "barbell back squat", "Leg day")
    r = logged_in.post(
        "/confirm",
        data={
            "date": DAY,
            "title": "Evening walk",
            "num_entries": "0",
            "num_cardio": "1",
            "cardio-0-activity": "walking",
            "cardio-0-distance": "3 miles",
            "cardio-0-duration": "45 min",
            "cardio-0-notes": "",
        },
    )
    assert r.headers["Location"] == f"/?saved={DAY}&session=1#my-latest"
    with app.app_context():
        assert [(c.activity, c.session) for c in Cardio.query.all()] == [("walking", 1)]
        assert session_meta.get(USER, DAY, 1).title == "Evening walk"


def test_review_screen_offers_a_title_field(logged_in, fake_llm):
    fake_llm.queue(
        {
            "exercises": [
                {"exercise": "barbell back squat", "weight": "100 lbs", "sets": "3", "reps": "8"}
            ]
        }
    )
    body = logged_in.post("/review", data={"workout": "squats", "client_date": DAY}).data.decode()
    assert 'name="title"' in body and "Name this workout" in body


def test_migration_adds_session_columns_and_copies_per_day_tables(tmp_path):
    """An existing database from before sessions: old workout/cardio/comment tables
    without `session`, a one-title-per-day session_meta, per-day kudos."""
    from gymllm import create_app
    from tests.conftest import base_test_config

    path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as c:
        for stmt in (
            "CREATE TABLE workout (id INTEGER PRIMARY KEY, user_email VARCHAR NOT NULL, date VARCHAR NOT NULL, exercise VARCHAR NOT NULL, weight VARCHAR, sets VARCHAR, reps VARCHAR, notes VARCHAR, tags VARCHAR)",
            "CREATE TABLE cardio (id INTEGER PRIMARY KEY, user_email VARCHAR NOT NULL, date VARCHAR NOT NULL, activity VARCHAR NOT NULL, distance VARCHAR, duration VARCHAR, notes VARCHAR)",
            "CREATE TABLE comment (id INTEGER PRIMARY KEY, owner_email VARCHAR NOT NULL, date VARCHAR NOT NULL, author_email VARCHAR NOT NULL, body VARCHAR(500) NOT NULL, created_at DATETIME NOT NULL)",
            "CREATE TABLE session_meta (owner_email VARCHAR NOT NULL, date VARCHAR NOT NULL, title VARCHAR(80), photo_key VARCHAR, PRIMARY KEY (owner_email, date))",
            "CREATE TABLE kudos (id INTEGER PRIMARY KEY, owner_email VARCHAR NOT NULL, date VARCHAR NOT NULL, giver_email VARCHAR NOT NULL, created_at DATETIME NOT NULL, UNIQUE (owner_email, date, giver_email))",
            f"INSERT INTO workout (user_email, date, exercise) VALUES ('{USER}', '{DAY}', 'squat')",
            f"INSERT INTO session_meta VALUES ('{USER}', '{DAY}', 'Leg day', NULL)",
            f"INSERT INTO kudos (owner_email, date, giver_email, created_at) VALUES ('{USER}', '{DAY}', '{OTHER}', '2026-03-10 10:00:00')",
        ):
            c.execute(text(stmt))
    config = {**base_test_config(), "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}"}
    app = create_app(config)
    with app.app_context():
        for table in ("workout", "cardio", "comment"):
            assert "session" in {c["name"] for c in inspect(db.engine).get_columns(table)}
        assert Workout.query.one().session == 0
        assert session_meta.get(USER, DAY, 0).title == "Leg day"
        assert [(k.date, k.session, k.giver_email) for k in Kudos.query.all()] == [(DAY, 0, OTHER)]
        migrate.run()  # running it again changes nothing
        assert Kudos.query.count() == 1 and session_meta.get(USER, DAY, 0).title == "Leg day"


def test_activity_count_keeps_lifts_and_cardio_apart():
    from gymllm.sessions import activity_count

    lifts = [{"exercise": "squat"}, {"exercise": "squat"}, {"exercise": "curl"}]
    assert activity_count({"rows": lifts, "cardio": [{}]}) == "2 exercises · 1 cardio"
    assert activity_count({"rows": lifts[:1], "cardio": []}) == "1 exercise"
    assert activity_count({"rows": [], "cardio": [{}, {}]}) == "2 cardio"
