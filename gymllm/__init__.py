"""GymLLM application factory."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request, url_for
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

    from . import auth, routes, social_routes

    auth.init_app(app)
    app.register_blueprint(routes.bp)
    app.register_blueprint(social_routes.bp)

    _register_error_handlers(app)
    _register_context(app)

    with app.app_context():
        db.create_all()

    return app


def _register_context(app: Flask) -> None:
    from . import social
    from .auth import current_user_email
    from .llm.providers import PROVIDERS, LLMConfig

    @app.context_processor
    def inject_globals():
        email = current_user_email()
        my_profile = social.get_profile(email)
        return {
            "user_email": email,
            "my_profile": my_profile,
            "social_unseen": social.unseen_count(email) if my_profile else 0,
            "llm_config": LLMConfig.from_session(),
            "providers": PROVIDERS,
            "site_llm": app.config.get("SITE_LLM"),
        }

    @app.template_filter("nice_date")
    def nice_date(value: str) -> str:
        """'2026-02-01' -> 'Sun 1 Feb 2026'; anything unparsable is returned as is."""
        try:
            d = date.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return f"{d:%a} {d.day} {d:%b %Y}"

    @app.template_filter("fmt_num")
    def fmt_num(value) -> str:
        """12345.0 -> '12,345'; 12.5 -> '12.5'; None -> ''."""
        if value is None or value == "":
            return ""
        n = float(value)
        return f"{n:,.0f}" if n == int(n) else f"{n:,.1f}"

    @app.template_filter("ago")
    def ago(value) -> str:
        """A naive-UTC datetime as '5m', '3h', '2d', or '4 Sep' once over a week old."""
        if not isinstance(value, datetime):
            return ""
        secs = (datetime.now(timezone.utc).replace(tzinfo=None) - value).total_seconds()
        if secs < 60:
            return "now"
        if secs < 3600:
            return f"{int(secs // 60)}m"
        if secs < 86400:
            return f"{int(secs // 3600)}h"
        if secs < 7 * 86400:
            return f"{int(secs // 86400)}d"
        return f"{value.day} {value:%b}"

    @app.template_global("period_url")
    def period_url(**changes) -> str:
        """The current page's URL with some query args replaced (range=, by=)."""
        args = {**(request.view_args or {}), **request.args.to_dict(), **changes}
        return url_for(request.endpoint, **{k: v for k, v in args.items() if v is not None})


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
