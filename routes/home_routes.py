from flask import Blueprint, render_template_string, redirect, url_for
from flask_dance.contrib.google import google
from utils.taglist import exerciseListText
from app import HTML_TEMPLATE

home_bp = Blueprint('home_bp', __name__)

@home_bp.route("/", methods=["GET"])
def home():
    user_email = None
    if google.authorized:
        try:
            resp = google.get("/oauth2/v2/userinfo")
            if resp.ok:
                user_email = resp.json().get("email")
        except Exception:
            pass
    return render_template_string(
        HTML_TEMPLATE,
        submitted=False,
        workout_text="",
        parsed_output=None,
        log_status="",
        user_email=user_email
    )
