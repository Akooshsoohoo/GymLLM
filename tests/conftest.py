import pytest

from gymllm import create_app
from gymllm.extensions import db
from gymllm.llm.client import BadOutputError, LLMError
from gymllm.models import Workout

USER = "tester@example.com"
OTHER = "someone-else@example.com"

LLM_SESSION = {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test", "base_url": ""}


class FakeLLM:
    """Stand-in for a provider client. Queue responses; raise LLMErrors on demand."""

    def __init__(self):
        self.responses = []
        self.calls = []
        self.error = None

    def queue(self, *responses):
        self.responses.extend(responses)
        return self

    def complete_json(self, system, user):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        if not self.responses:
            return {"date": None, "exercises": []}
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def list_models(self):
        return ["llama3.2", "mistral"]


def base_test_config():
    return {
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "WTF_CSRF_ENABLED": False,
        "GOOGLE_OAUTH_CLIENT_ID": "x",
        "GOOGLE_OAUTH_CLIENT_SECRET": "y",
        "IS_PRODUCTION": False,
    }


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def app(fake_llm):
    app = create_app(base_test_config())
    app.config["LLM_CLIENT_FACTORY"] = lambda config: fake_llm
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in(client):
    with client.session_transaction() as s:
        s["user_email"] = USER
        s["llm"] = dict(LLM_SESSION)
    return client


@pytest.fixture
def add_workout(app):
    def _add(**kwargs):
        defaults = {
            "user_email": USER,
            "date": "2026-01-10",
            "exercise": "barbell bench press",
            "weight": "185 lbs",
            "sets": "5",
            "reps": "5, 5, 5, 5, 5",
            "notes": "",
            "tags": "chest;push",
        }
        defaults.update(kwargs)
        with app.app_context():
            w = Workout(**defaults)
            db.session.add(w)
            db.session.commit()
            return w.id

    return _add


__all__ = ["BadOutputError", "LLMError"]
