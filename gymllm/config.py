"""Environment-driven configuration for the Flask app."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import timedelta


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing or invalid."""


DEFAULT_SITE_LLM_PROVIDER = "groq"
DEFAULT_SITE_LLM_DAILY_LIMIT = 20


def site_llm_config(env: Mapping[str, str]) -> dict | None:
    """The owner-provided shared model (SITE_LLM_* variables), or None if not set up.

    The key never reaches users: sessions only record provider="site" and the
    real provider/model/key are looked up here when a call is made.
    """
    api_key = env.get("SITE_LLM_API_KEY", "").strip()
    if not api_key:
        return None
    from .llm.providers import PROVIDERS  # local import: providers imports flask, keep config light

    provider = env.get("SITE_LLM_PROVIDER", "").strip() or DEFAULT_SITE_LLM_PROVIDER
    info = PROVIDERS.get(provider)
    if info is None or info.is_local or provider == "site":
        raise ConfigError(f"SITE_LLM_PROVIDER must be a hosted provider, not {provider!r}.")
    base_url = env.get("SITE_LLM_BASE_URL", "").strip()
    if provider == "custom" and not base_url.startswith(("http://", "https://")):
        raise ConfigError("SITE_LLM_BASE_URL is required (http:// or https://) for custom.")
    raw_limit = env.get("SITE_LLM_DAILY_LIMIT", "").strip()
    try:
        daily_limit = int(raw_limit) if raw_limit else DEFAULT_SITE_LLM_DAILY_LIMIT
    except ValueError as e:
        raise ConfigError("SITE_LLM_DAILY_LIMIT must be a whole number.") from e
    if daily_limit < 1:
        raise ConfigError("SITE_LLM_DAILY_LIMIT must be at least 1.")
    return {
        "provider": provider,
        "model": env.get("SITE_LLM_MODEL", "").strip() or info.default_model,
        "api_key": api_key,
        "base_url": base_url,
        "daily_limit": daily_limit,
    }


def is_production(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("FLASK_ENV", "").lower() == "production" or env.get("RENDER", "") == "true"


def build_config(env: Mapping[str, str] | None = None) -> dict:
    """Build the Flask config dict from environment variables.

    Locally, DATABASE_URL is optional and falls back to a SQLite file in the
    instance folder. In production (FLASK_ENV=production or on Render) both
    FLASK_SECRET_KEY and DATABASE_URL are required.
    """
    env = os.environ if env is None else env
    prod = is_production(env)

    secret = env.get("FLASK_SECRET_KEY")
    if not secret:
        raise ConfigError("FLASK_SECRET_KEY environment variable is not set.")

    db_url = env.get("DATABASE_URL")
    if not db_url:
        if prod:
            raise ConfigError("DATABASE_URL environment variable is not set.")
        # Relative SQLite paths resolve against app.instance_path.
        db_url = "sqlite:///gymllm.db"
    elif db_url.startswith("postgres://"):
        # Older Render/Heroku URLs use a scheme SQLAlchemy 2 rejects.
        db_url = "postgresql://" + db_url[len("postgres://") :]

    return {
        "SECRET_KEY": secret,
        "IS_PRODUCTION": prod,
        "SQLALCHEMY_DATABASE_URI": db_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": prod,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=30),
        "PREFERRED_URL_SCHEME": "https" if prod else "http",
        "WTF_CSRF_TIME_LIMIT": None,
        # Flask-Dance reads these keys when the Google blueprint is registered.
        "GOOGLE_OAUTH_CLIENT_ID": env.get("GOOGLE_CLIENT_ID", ""),
        "GOOGLE_OAUTH_CLIENT_SECRET": env.get("GOOGLE_CLIENT_SECRET", ""),
        "SITE_LLM": site_llm_config(env),
    }
