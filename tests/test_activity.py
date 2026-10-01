from gymllm import activity
from gymllm.models import ParseLog, UserActivity

USER = "tester@example.com"
OTHER = "someone-else@example.com"


def test_touch_creates_then_does_not_duplicate_same_day(app):
    with app.app_context():
        activity.touch(USER)
        activity.touch(USER)
        assert UserActivity.query.filter_by(user_email=USER).count() == 1
        assert UserActivity.query.get(USER).last_active_date == activity.today()


def test_active_counts(app):
    with app.app_context():
        activity.touch(USER)
        activity.touch(OTHER)
        counts = activity.active_counts()
        assert counts == {"today": 2, "this_week": 2}


def test_record_parse_accumulates_same_day(app):
    with app.app_context():
        activity.record_parse(USER)
        activity.record_parse(USER)
        activity.record_parse(OTHER)
        row = ParseLog.query.filter_by(user_email=USER, day=activity.today()).first()
        assert row.count == 2
        assert activity.parses_today() == 3


def test_parses_today_is_zero_with_no_rows(app):
    with app.app_context():
        assert activity.parses_today() == 0


def test_logged_in_request_touches_activity(logged_in):
    logged_in.get("/")
    from gymllm.models import UserActivity as UA

    with logged_in.application.app_context():
        assert UA.query.filter_by(user_email="tester@example.com").count() == 1
