from flask import Blueprint, render_template, request
import json
from utils.utils import parse_workout_input
from utils.taglist import exerciseListText

review_bp = Blueprint('review_bp', __name__)

@review_bp.route("/review", methods=["POST"])
def review():
    workout_text = request.form.get("workout", "")
    parsed_output = parse_workout_input(workout_text)
    try:
        parsed_data = json.loads(parsed_output)
        pretty_json = json.dumps(parsed_data, indent=2)
        error = None
    except Exception:
        pretty_json = None
        if parsed_output and "?" in parsed_output and len(parsed_output) < 150:
            error = f"LLM responded with: {parsed_output}"
        else:
            error = "Could not parse the workout. LLM responded with a question or invalid format."
    return render_template("review.html",
        workout_text=workout_text,
        pretty_json=pretty_json,
        error=error,
        parsed_output=parsed_output
    )
