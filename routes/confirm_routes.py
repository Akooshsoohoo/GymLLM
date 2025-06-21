from flask import Blueprint, render_template_string, request
from flask_dance.contrib.google import google
from models.models import db, Workout
from utils import find_best_match
from utils.taglist import tag_df
from app import SAVED_TEMPLATE
import json
from datetime import datetime

confirm_bp = Blueprint('confirm_bp', __name__)

@confirm_bp.route("/confirm", methods=["POST"])
def confirm():
    workout_text = request.form.get("workout_text", "")
    parsed_output = request.form.get("parsed_output", "")
    try:
        parsed_data = json.loads(parsed_output)
    except Exception as e:
        return f"Failed to parse data for saving: {e}", 400
    user_email = None
    if google.authorized:
        try:
            resp = google.get("/oauth2/v2/userinfo")
            if resp.ok:
                user_email = resp.json().get("email")
        except Exception:
            pass
    if not user_email:
        return "Not logged in", 401
    today_str = datetime.now().strftime("%Y-%m-%d")
    for entry in parsed_data:
        matched_name, tags = find_best_match(entry.get("exercise", ""), tag_df)
        workout = Workout(
            user_email=user_email,
            date=today_str,
            exercise=matched_name,
            weight=entry.get("weight", ""),
            sets=entry.get("sets", ""),
            reps=entry.get("reps", ""),
            notes=entry.get("notes", ""),
            tags=tags
        )
        db.session.add(workout)
    db.session.commit()
    pretty_json = json.dumps(parsed_data, indent=2)
    return render_template_string(
        SAVED_TEMPLATE,
        pretty_json=pretty_json
    )
