"""GymLLM application factory."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import build_config
from .extensions import csrf, db

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv(BASE_DIR / ".env")

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
        instance_path=str(BASE_DIR / "instance"),
    )
    if test_config is None:
        app.config.update(build_config())
    else:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    # Render terminates TLS in front of the app; trust its forwarding headers so
    # url_for(_external=True) and Secure cookies see https.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)

    from .llm.client import get_client

    app.config.setdefault("LLM_CLIENT_FACTORY", get_client)

    from . import auth, routes

    auth.init_app(app)
    app.register_blueprint(routes.bp)

    _register_error_handlers(app)
    _register_context(app)

    with app.app_context():
        db.create_all()

    return app


def _register_context(app: Flask) -> None:
    from .auth import current_user_email
    from .llm.providers import PROVIDERS, LLMConfig

    @app.context_processor
    def inject_globals():
        return {
            "user_email": current_user_email(),
            "llm_config": LLMConfig.from_session(),
            "providers": PROVIDERS,
        }

    @app.template_filter("nice_date")
    def nice_date(value: str) -> str:
        """'2026-02-01' -> 'Sun 1 Feb 2026'; anything unparsable is returned as is."""
        try:
            d = date.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return f"{d:%a} {d.day} {d:%b %Y}"


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(CSRFError)
    def csrf_failed(e):
        return render_template("errors/400.html", message=e.description), 400

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Unhandled error: %s", e)
        return render_template("errors/500.html"), 500
