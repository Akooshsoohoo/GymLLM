"""Signing in: a Google ID token from the iOS SDK, or a seeded dev account, is
exchanged for the API's own bearer token."""

from __future__ import annotations

from flask import current_app, jsonify

from .. import auth, dev_routes
from . import bp, dev_bp
from .core import me_payload
from .errors import ApiError, json_body, not_found


def verify_google_id_token(token: str, audience: str) -> dict:
    """The token's claims if Google signed it for our iOS client; ValueError if not."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)


def _signed_in(email: str, name: str, picture: str = ""):
    token = auth.issue_api_token(email, name, picture)
    return jsonify(token=token, user=me_payload(email, name))


@bp.route("/auth/google", methods=["POST"])
def auth_google():
    audience = current_app.config.get("GOOGLE_IOS_CLIENT_ID")
    if not audience:
        raise ApiError(503, "not_configured", "Google sign-in isn't set up yet.")
    raw = json_body().get("id_token")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "bad_request", "id_token is required.")
    verify = current_app.config.get("GOOGLE_ID_TOKEN_VERIFIER", verify_google_id_token)
    try:
        claims = verify(raw.strip(), audience)
    except ValueError:
        raise ApiError(401, "invalid_token", "Google sign-in didn't work. Try again.") from None
    except Exception:  # noqa: BLE001 - Google's certificates could not be fetched, ...
        current_app.logger.exception("Could not verify a Google ID token")
        raise ApiError(503, "google_unavailable", "Couldn't reach Google. Try again.") from None
    email = claims.get("email")
    if not email or claims.get("email_verified") is not True:
        raise ApiError(401, "email_unverified", "That Google account has no verified email.")
    return _signed_in(email, claims.get("name") or "", claims.get("picture") or "")


@dev_bp.route("/auth/dev", methods=["POST"])
def auth_dev():
    """A token for one of the seeded dev accounts, so the app can be built and run
    before Google sign-in is configured."""
    slug = json_body().get("slug")
    user = next((u for u in dev_routes.DEV_USERS if u["slug"] == slug), None)
    if user is None:
        raise not_found("No such dev account.")
    dev_routes._ensure_seeded()
    return _signed_in(user["email"], user["display_name"])
