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
        self.configs = []  # every LLMConfig the client factory was asked for
        self.error = None

    def for_config(self, config):
        self.configs.append(config)
        return self

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
        "SITE_LLM": None,
    }


SITE_LLM = {
    "provider": "groq",
    "model": "openai/gpt-oss-120b",
    "api_key": "gsk-site",
    "base_url": "",
    "daily_limit": 2,
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
def site_app(fake_llm):
    """An app whose owner configured a shared model with a cap of 2 parses a day."""
    cfg = base_test_config()
    cfg["SITE_LLM"] = dict(SITE_LLM)
    app = create_app(cfg)
    app.config["LLM_CLIENT_FACTORY"] = lambda config: fake_llm.for_config(config)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def site_user(site_app):
    """Signed in on the shared-model app with no provider chosen."""
    client = site_app.test_client()
    with client.session_transaction() as s:
        s["user_email"] = USER
    return client


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
