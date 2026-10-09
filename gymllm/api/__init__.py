"""The JSON API the iOS app talks to, at /api/v1. It authenticates with bearer
tokens (never the cookie session), answers only in JSON, and each endpoint mirrors
one page handler in routes.py or social_routes.py."""

from __future__ import annotations

from flask import Blueprint

from ..extensions import csrf

bp = Blueprint("api", __name__, url_prefix="/api/v1")
# Registered only where dev_routes is: never in production, only on SQLite.
dev_bp = Blueprint("api_dev", __name__, url_prefix="/api/v1")

# No cookies, so nothing for a forged cross-site request to ride on.
csrf.exempt(bp)
csrf.exempt(dev_bp)

from . import errors  # noqa: E402

errors.register(bp)
errors.register(dev_bp)

from . import account, auth_routes, core, friends, progress, record  # noqa: E402, F401
