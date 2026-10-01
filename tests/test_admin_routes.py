from gymllm import create_app
from gymllm.extensions import db
from gymllm.models import Workout

from .conftest import USER, base_test_config


def _admin_app(admin_emails):
    return create_app({**base_test_config(), "ADMIN_EMAILS": admin_emails})


def test_anonymous_is_redirected_to_welcome():
    app = _admin_app({USER})
    r = app.test_client().get("/admin/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_logged_in_non_admin_gets_404():
    app = _admin_app(set())
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = USER
    assert client.get("/admin/").status_code == 404
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_admin_sees_dashboard_with_seeded_counts():
    app = _admin_app({USER})
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = USER
    with app.app_context():
        db.session.add(
            Workout(
                user_email=USER,
                date="2026-01-10",
                exercise="back squat",
                weight="185 lbs",
                sets="5",
                reps="5",
            )
        )
        db.session.commit()

    r = client.get("/admin/")
    assert r.status_code == 200
    assert USER.encode() in r.data
    with app.app_context():
        db.session.remove()
        db.drop_all()
