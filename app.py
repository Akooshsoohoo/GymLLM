import os
from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, redirect, url_for, session,
    request, render_template_string
)
from flask_dance.contrib.google import make_google_blueprint, google
from flask_sqlalchemy import SQLAlchemy

import json
from datetime import datetime
from openai import OpenAI

# ---------- LLM helpers ----------
from main import (
    parse_workout_input,
    exerciseListText,
    find_best_match,
    tag_df,
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------- Flask setup ----------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersekrit")

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    exercise = db.Column(db.String, nullable=False)
    weight = db.Column(db.String)
    sets = db.Column(db.String)
    reps = db.Column(db.String)
    notes = db.Column(db.String)
    tags = db.Column(db.String)


# ---------- Google OAuth ----------
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ],
    redirect_to="oauth_success",
)
app.register_blueprint(google_bp, url_prefix="/login")

# ---------- HTML templates (unchanged except extra Delete col & hidden id) ----------
# … [REVIEW_TEMPLATE, SAVED_TEMPLATE, HTML_TEMPLATE unchanged] …
# … SEARCH_TEMPLATE includes a final <th>Delete</th> column, a checkbox,
#   and now also a hidden input 'id-{{i}}' per row …

REVIEW_TEMPLATE = """ (unchanged, omitted for brevity) """
SAVED_TEMPLATE  = """ (unchanged, omitted for brevity) """
HTML_TEMPLATE   = """ (unchanged, omitted for brevity) """

SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>Search Workout Log</title>
<style> /* … styles unchanged … */ </style>
</head>
<body>
    <h1>Search Your Workout Log</h1>
    <form method="get" style="margin-bottom:16px;">
        <label for="query">Search (name or tag):</label>
        <input type="text" id="query" name="query"
               value="{{ query|default('') }}" style="width:60%;">
        <input type="submit" value="Search">
    </form>

    <form method="post" action="/search">
        <table>
            <tr>
                <th>Date</th><th>Exercise</th><th>Weight</th><th>Sets</th>
                <th>Reps</th><th>Notes</th><th>Tags</th><th>Delete</th>
            </tr>
            {% for i in range(rows|length) %}
            <tr>
                {% for j in range(7) %}
                <td>
                    <input type="text"
                           name="cell-{{i}}-{{j}}"
                           value="{{ rows[i][j] }}">
                </td>
                {% endfor %}
                <td style="text-align:center;">
                    <input type="checkbox" name="delete-{{i}}">
                    <input type="hidden" name="id-{{i}}" value="{{ rows[i][7] }}">
                </td>
            </tr>
            {% endfor %}
        </table>
        <input type="hidden" name="num_rows" value="{{ rows|length }}">
        <input type="submit" value="Save Changes">
    </form>
    <br><a href="/">Back to Log Input</a>

    <script>
        // simple unsaved-changes warning (unchanged) …
    </script>
</body>
</html>
"""

# ---------- Helpers ----------
def _current_user_email() -> str | None:
    if not google.authorized:
        return None
    try:
        resp = google.get("/oauth2/v2/userinfo")
        if resp.ok:
            return resp.json().get("email")
    except Exception:
        pass
    return None


# ---------- Routes ----------
@app.before_request
def _fix_google_token_expires():
    tok = google_bp.token
    if tok and "expires_in" in tok and not isinstance(tok["expires_in"], int):
        try:
            tok["expires_in"] = int(float(tok["expires_in"]))
        except Exception:
            tok["expires_in"] = 0
        google_bp.token = tok
        google_bp.session.token = tok
        session[f"{google_bp.name}_oauth_token"] = tok


@app.route("/login")
def login():
    return redirect(url_for("google.login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/oauth_success")
def oauth_success():
    return redirect(url_for("home"))


@app.route("/", methods=["GET"])
def home():
    return render_template_string(
        HTML_TEMPLATE,
        user_email=_current_user_email()
    )


@app.route("/search", methods=["GET", "POST"])
def search():
    user = _current_user_email()
    if not user:
        return redirect(url_for("login"))

    # -------- handle POST (save edits / deletes) --------
    if request.method == "POST":
        num_rows = int(request.form.get("num_rows", 0))

        for i in range(num_rows):
            row_id   = int(request.form.get(f"id-{i}", 0))
            to_delete = request.form.get(f"delete-{i}") is not None
            workout = Workout.query.get(row_id)

            if not workout or workout.user_email != user:
                continue  # skip anything weird

            if to_delete:
                db.session.delete(workout)
                continue

            # update fields
            workout.date     = request.form.get(f"cell-{i}-0", workout.date)
            workout.exercise = request.form.get(f"cell-{i}-1", workout.exercise)
            workout.weight   = request.form.get(f"cell-{i}-2", workout.weight)
            workout.sets     = request.form.get(f"cell-{i}-3", workout.sets)
            workout.reps     = request.form.get(f"cell-{i}-4", workout.reps)
            workout.notes    = request.form.get(f"cell-{i}-5", workout.notes)
            workout.tags     = request.form.get(f"cell-{i}-6", workout.tags)

        db.session.commit()
        return redirect(url_for("search", query=request.args.get("query", "")))

    # -------- handle GET (load/search) --------
    query = request.args.get("query", "").lower()

    q = Workout.query.filter_by(user_email=user)
    if query:
        q = q.filter(
            (Workout.exercise.ilike(f"%{query}%"))
            | (Workout.tags.ilike(f"%{query}%"))
            | (Workout.notes.ilike(f"%{query}%"))
        )
    workouts = q.order_by(Workout.date.desc()).all()

    rows = [
        [
            w.date, w.exercise, w.weight, w.sets,
            w.reps, w.notes, w.tags, w.id
        ]
        for w in workouts
    ]
    return render_template_string(SEARCH_TEMPLATE, rows=rows, query=query)


@app.route("/review", methods=["POST"])
def review():
    workout_text = request.form.get("workout", "")
    parsed_output = parse_workout_input(workout_text, client, exerciseListText)
    try:
        parsed_data = json.loads(parsed_output)
        pretty_json, error = json.dumps(parsed_data, indent=2), None
    except Exception:
        pretty_json, error = None, "Could not parse the workout."
    return render_template_string(
        REVIEW_TEMPLATE,
        workout_text=workout_text,
        pretty_json=pretty_json,
        error=error,
        parsed_output=parsed_output,
    )


@app.route("/confirm", methods=["POST"])
def confirm():
    parsed_output = request.form.get("parsed_output", "")
    try:
        parsed_data = json.loads(parsed_output)
    except Exception as e:
        return f"Bad data: {e}", 400

    user = _current_user_email()
    if not user:
        return "Not logged in", 401

    today = datetime.now().strftime("%Y-%m-%d")
    for entry in parsed_data:
        name, tags = find_best_match(entry.get("exercise", ""), tag_df)
        db.session.add(
            Workout(
                user_email=user,
                date=today,
                exercise=name,
                weight=entry.get("weight", ""),
                sets=entry.get("sets", ""),
                reps=entry.get("reps", ""),
                notes=entry.get("notes", ""),
                tags=tags,
            )
        )
    db.session.commit()

    return render_template_string(
        SAVED_TEMPLATE,
        pretty_json=json.dumps(parsed_data, indent=2),
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
