from gymllm import create_app
from gymllm.extensions import db
from gymllm.models import Workout

from .conftest import base_test_config


def test_dev_routes_absent_in_production():
    app = create_app({**base_test_config(), "IS_PRODUCTION": True})
    client = app.test_client()
    assert client.get("/dev/").status_code == 404
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_login_sets_session_and_redirects_home(client):
    r = client.get("/dev/login/alex", follow_redirects=True)
    assert r.status_code == 200
    with client.session_transaction() as s:
        assert s["user_email"] == "dev-alex@example.test"


def test_login_seeds_workouts_and_friends(app, client):
    client.get("/dev/login/alex")
    with app.app_context():
        assert Workout.query.filter_by(user_email="dev-alex@example.test").count() > 0

    from gymllm import social

    with app.app_context():
        assert (
            social.relationship("dev-alex@example.test", "dev-sam@example.test") == social.FRIENDS
        )


def test_login_twice_does_not_duplicate_seed_data(app, client):
    client.get("/dev/login/alex")
    with app.app_context():
        first_count = Workout.query.filter_by(user_email="dev-alex@example.test").count()

    client.get("/dev/login/sam")
    with app.app_context():
        second_count = Workout.query.filter_by(user_email="dev-alex@example.test").count()

    assert first_count == second_count


def test_unknown_slug_redirects_to_index(client):
    r = client.get("/dev/login/nobody")
    assert r.status_code == 302 and r.headers["Location"].endswith("/dev/")
