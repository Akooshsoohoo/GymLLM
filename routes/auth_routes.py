from flask import Blueprint, redirect, url_for, session
from flask_dance.contrib.google import google

auth_bp = Blueprint('auth', __name__)

@auth_bp.before_app_request
def _fix_google_token_expires():
    from app import google_bp
    token = google_bp.token
    if token and "expires_in" in token and not isinstance(token["expires_in"], int):
        try:
            token["expires_in"] = int(float(token["expires_in"]))
        except (ValueError, TypeError):
            token["expires_in"] = 0
        google_bp.token = token
        google_bp.session.token = token
        session[f"{google_bp.name}_oauth_token"] = token

@auth_bp.route("/login")
def login():
    if google.authorized:
        return redirect(url_for("home_bp.home"))
    return redirect(url_for("google.login"))

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("https://accounts.google.com/Logout?continue=https://appengine.google.com/_ah/logout?continue=" + url_for("home_bp.home", _external=True))

@auth_bp.route("/oauth_success")
def oauth_success():
    return redirect(url_for("home_bp.home"))
