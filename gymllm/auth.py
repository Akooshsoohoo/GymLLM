"""Google sign-in via Flask-Dance, with the user's email cached in the session."""

from __future__ import annotations

from functools import wraps

import requests
from flask import Blueprint, flash, redirect, request, session, url_for
from flask_dance.contrib.google import google, make_google_blueprint

SESSION_EMAIL = "user_email"
SESSION_GOOGLE_NAME = "google_name"  # prefills profile setup
SESSION_GOOGLE_PICTURE = "google_picture"
AFTER_LOGIN = "after_login"  # a relative path to return to once signed in
AUTH_SESSION_KEYS = (
    SESSION_EMAIL,
    SESSION_GOOGLE_NAME,
    SESSION_GOOGLE_PICTURE,
    "google_oauth_token",
)

bp = Blueprint("auth", __name__)

google_bp = make_google_blueprint(
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ],
    redirect_to="auth.oauth_success",
)


def init_app(app) -> None:
    app.register_blueprint(google_bp, url_prefix="/login")
    app.register_blueprint(bp)


def _clear_auth() -> None:
    for key in AUTH_SESSION_KEYS:
        session.pop(key, None)
    try:
        del google_bp.token
    except Exception:  # noqa: BLE001 - token may already be gone
        pass


def current_user_email() -> str | None:
    """Return the signed-in user's email, or None.

    The email is cached in the session after the first successful userinfo
    call so normal page loads never hit Google. An expired or revoked token
    clears the cached state so the next request lands on the welcome page.
    """
    email = session.get(SESSION_EMAIL)
    if email:
        return email
    if not google.authorized:
        return None
    try:
        resp = google.get("/oauth2/v2/userinfo", timeout=5)
    except Exception:  # noqa: BLE001 - TokenExpiredError, network errors, ...
        _clear_auth()
        return None
    if resp.ok:
        info = resp.json()
        email = info.get("email")
        if email:
            session[SESSION_EMAIL] = email
            session[SESSION_GOOGLE_NAME] = info.get("name") or ""
            session[SESSION_GOOGLE_PICTURE] = info.get("picture") or ""
            session.permanent = True
            return email
    if resp.status_code in (401, 403):
        _clear_auth()
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_email():
            return redirect(url_for("main.welcome"))
        return view(*args, **kwargs)

    return wrapped


@bp.before_app_request
def _fix_google_token_expires():
    """Google sometimes returns expires_in as a float, which oauthlib rejects."""
    if request.endpoint == "static":
        return
    token = google_bp.token
    if token and "expires_in" in token and not isinstance(token["expires_in"], int):
        try:
            token["expires_in"] = int(float(token["expires_in"]))
        except (ValueError, TypeError):
            token["expires_in"] = 0
        google_bp.token = token


@bp.route("/login")
def login():
    if current_user_email():
        return redirect(url_for("main.home"))
    return redirect(url_for("google.login"))


def safe_next(path: str | None) -> str | None:
    """Only same-site relative paths such as /invite/abc, never //host or a full URL."""
    if path and path.startswith("/") and not path.startswith(("//", "/\\")):
        return path
    return None


@bp.route("/oauth_success")
def oauth_success():
    return redirect(safe_next(session.pop(AFTER_LOGIN, None)) or url_for("main.home"))


@bp.route("/logout")
def logout():
    token = google_bp.token or {}
    access_token = token.get("access_token")
    if access_token:
        # Best effort: revoke only this app's grant, not the user's Google session.
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": access_token},
                timeout=3,
            )
        except requests.RequestException:
            pass
    _clear_auth()
    flash("You have been signed out.", "ok")
    return redirect(url_for("main.welcome"))
