import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, session, request, render_template_string
from flask_dance.contrib.google import make_google_blueprint, google

from flask_sqlalchemy import SQLAlchemy

import csv
import json
import pandas as pd
from datetime import datetime
from openai import OpenAI

# Import your parsing and matching functions
from main import parse_workout_input, exerciseListText, find_best_match, tag_df

# Set up OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- BEGIN OAUTH SETUP -------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersekrit")



app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    exercise = db.Column(db.String, nullable=False)
    weight = db.Column(db.String, nullable=True)
    sets = db.Column(db.String, nullable=True)
    reps = db.Column(db.String, nullable=True)
    notes = db.Column(db.String, nullable=True)
    tags = db.Column(db.String, nullable=True)



google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ],
    # After Google finishes, jump to /oauth_success (defined just below)
    redirect_to="oauth_success",
)
app.register_blueprint(google_bp, url_prefix="/login")
# --- END  OAUTH SETUP --------------------------------------------------


# --------- HTML templates ----------

REVIEW_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    <title>Review & Confirm Workout</title>
</head>
<body>
    <div class="nav">
        <a href="/">Log Workout</a>
        <a href="/search">Search/Filter Log</a>
    </div>
    <h1>Review & Confirm Workout</h1>
    {% if error %}
        <div class="status">{{ error }}</div>
    {% endif %}
    <form method="post" action="/review">
        <label for="workout">Edit your original workout prompt:</label><br>
        <textarea id="workout" name="workout" rows="4" cols="50">{{ workout_text }}</textarea><br>
        <input type="submit" value="Re-Parse & Review">
    </form>
    {% if pretty_json %}
        <h2>LLM Parsed Output:</h2>
        <pre>{{ pretty_json }}</pre>
        <form method="post" action="/confirm">
            <input type="hidden" name="workout_text" value="{{ workout_text }}">
            <input type="hidden" name="parsed_output" value="{{ parsed_output }}">
            <button type="submit">Approve & Save to Log</button>
        </form>
    {% endif %}
</body>
</html>
"""

SAVED_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Workout Saved!</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="nav">
        <a href="/">Log Another</a>
        <a href="/search">Search Log</a>
    </div>
    <h1>Workout Saved!</h1>
    <div class="status">
        Your workout has been successfully logged.
    </div>
    <h2>What You Just Logged:</h2>
    <pre>{{ pretty_json }}</pre>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>GymLLM Workout Logger</title>
<style>
    .topright {
        position: absolute;
        top: 16px;
        right: 24px;
    }
</style>
</head>
<body>
    <div class="topright">
        {% if user_email %}
            <span style="margin-right:10px;">{{ user_email }}</span>
            <a href="/logout">Logout</a>
        {% else %}
            <a href="/login">Create Account / Login</a>
        {% endif %}
    </div>
    <div class="nav">
        <a href="/search">Search/Filter Log</a>
    </div>
    <h1>GymLLM</h1>
    <form method="post" action="/review">
        <label for="workout">Workout:</label><br>
        <textarea id="workout" name="workout" rows="4" cols="50" placeholder="e.g. bench 185 for 5x5, lat pulldowns 3x10, etc."></textarea><br>
        <input type="submit" value="Submit">
    </form>
</body>
</html>
"""


SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>Search Workout Log</title>
<style>
    table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 10px;
    }
    th, td {
        border: 1px solid #bbb;
        padding: 8px;
        text-align: left;
        font-size: 1rem;
    }
    th {
        background: #e0e9f3;
        font-weight: bold;
    }
    input[type="text"] {
        width: 100%;
        box-sizing: border-box;
        font-size: 1rem;
        padding: 5px 4px;
        border: 1px solid #d2d2d2;
        border-radius: 5px;
        background: #f9f9fc;
    }
    input[type="submit"], button {
        margin-top: 10px;
        padding: 8px 18px;
        font-size: 1rem;
        background: #2288c7;
        color: #fff;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        transition: background 0.15s;
    }
    input[type="submit"]:hover, button:hover {
        background: #1e6ea3;
    }
    body {
        font-family: "Segoe UI", Arial, sans-serif;
    }
    .nav, a {
        font-size: 1rem;
    }
</style>
</head>
<body>
    <h1>Search Your Workout Log</h1>
    <form method="get" style="margin-bottom: 16px;">
        <label for="query">Search (name or tag):</label>
        <input type="text" id="query" name="query" value="{{ query|default('') }}" style="width:60%;">
        <input type="submit" value="Search">
    </form>
    <form method="post" action="/search">
        <table>
            <tr>
                <th>Date</th>
                <th>Exercise</th>
                <th>Weight</th>
                <th>Sets</th>
                <th>Reps</th>
                <th>Notes</th>
                <th>Tags</th>
                <th>Delete</th>
            </tr>
            {% for i in range(rows|length) %}
            <tr>
                {% for j in range(rows[i]|length) %}
                <td>
                    <input type="text" name="cell-{{i}}-{{j}}" value="{{ rows[i][j] }}">
                </td>
                {% endfor %}
                <td style="text-align: center;">
                <input type="checkbox" name="delete-{{i}}">
                </td>
            </tr>
            {% endfor %}
        </table>
        <input type="hidden" name="num_rows" value="{{ rows|length }}">
        <input type="hidden" name="num_cols" value="{{ rows[0]|length if rows else 7 }}">
        <input type="submit" value="Save Changes">
    </form>
    <br>
    <a href="/">Back to Log Input</a>

    <script>
        document.addEventListener("DOMContentLoaded", function () {
            let changed = false;
            const inputs = document.querySelectorAll("form[action='/search'] input[type='text']");
            const saveButton = document.querySelector("form[action='/search'] input[type='submit']");
            const form = document.querySelector("form[action='/search']");

            // Hide Save button initially
            saveButton.style.display = "none";

            // If anything is typed, mark as changed
            inputs.forEach(input => {
                input.addEventListener("input", () => {
                    if (!changed) {
                        changed = true;
                        saveButton.style.display = "inline-block";
                    }
                });
            });

            // Cancel warning on form submission
            form.addEventListener("submit", () => {
                changed = false;
            });

            // Trigger warning if user tries to leave with unsaved edits
            window.addEventListener("beforeunload", function (e) {
                if (changed) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });
        });
    </script>
</body>
</html>
"""

# --------- Routes ---------


@app.before_request
def _fix_google_token_expires():
    token = google_bp.token
    if token and "expires_in" in token and not isinstance(token["expires_in"], int):
        try:
            token["expires_in"] = int(float(token["expires_in"]))
        except (ValueError, TypeError):
            token["expires_in"] = 0          # force refresh next time
        # write back everywhere Flask-Dance looks
        google_bp.token = token
        google_bp.session.token = token
        session[f"{google_bp.name}_oauth_token"] = token

@app.route("/login")
def login():
    if google.authorized:
        return redirect(url_for("home"))
    return redirect(url_for("google.login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/oauth_success")
def oauth_success():
    """
    User lands here immediately after Google OAuth succeeds.
    We don't need to do anything—just send them to the home page.
    """
    return redirect(url_for("home"))

@app.route("/", methods=["GET"])
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
@app.route("/search", methods=["GET", "POST"])
def search():
    # 1️⃣  make sure we know who is logged in
    user_email = None
    if google.authorized:
        try:
            resp = google.get("/oauth2/v2/userinfo")
            if resp.ok:
                user_email = resp.json().get("email")
        except Exception:
            pass

    if not user_email:
        return redirect(url_for("login"))

    # 2️⃣  handle edits / deletes coming back from the form -----------
    if request.method == "POST":
        num_rows = int(request.form.get("num_rows", 0))

        for i in range(num_rows):
            row_id   = request.form.get(f"id-{i}")          # hidden id field
            to_delete = request.form.get(f"delete-{i}")     # checkbox present if ticked

            if not row_id:          # should never happen
                continue

            workout = Workout.query.get(int(row_id))

            # sanity & ownership check
            if not workout or workout.user_email != user_email:
                continue

            if to_delete:
                db.session.delete(workout)
                continue           # no need to update if we’re deleting

            # update editable fields
            workout.date     = request.form.get(f"cell-{i}-0", "")
            workout.exercise = request.form.get(f"cell-{i}-1", "")
            workout.weight   = request.form.get(f"cell-{i}-2", "")
            workout.sets     = request.form.get(f"cell-{i}-3", "")
            workout.reps     = request.form.get(f"cell-{i}-4", "")
            workout.notes    = request.form.get(f"cell-{i}-5", "")
            workout.tags     = request.form.get(f"cell-{i}-6", "")

        db.session.commit()
        return redirect(url_for("search", query=request.args.get("query", "")))

    # 3️⃣  GET path → fetch rows for this user ------------------------
    query = request.values.get("query", "").lower()

    workouts_q = Workout.query.filter_by(user_email=user_email)
    if query:
        like = f"%{query}%"
        workouts_q = workouts_q.filter(
            db.or_(
                Workout.exercise.ilike(like),
                Workout.tags.ilike(like),
                Workout.notes.ilike(like)
            )
        )

    workouts = workouts_q.order_by(Workout.date.desc()).all()

    # 4️⃣  convert to list-of-lists for the template (last col = id)
    rows = [
        [
            w.date,
            w.exercise,
            w.weight,
            w.sets,
            w.reps,
            w.notes,
            w.tags,
            w.id          # 👈 keep id invisible but send back
        ]
        for w in workouts
    ]

    return render_template_string(SEARCH_TEMPLATE, rows=rows, query=query)

@app.route("/review", methods=["POST"])
def review():
    # Get the raw prompt—either from the first input or user edits
    workout_text = request.form.get("workout", "")
    # Always run LLM parse on current input
    parsed_output = parse_workout_input(workout_text, client, exerciseListText)
    # Try to parse as JSON
    try:
        parsed_data = json.loads(parsed_output)
        pretty_json = json.dumps(parsed_data, indent=2)
        error = None
    except Exception:
        pretty_json = None
        error = "Could not parse the workout. LLM responded with a question or invalid format."
    return render_template_string(REVIEW_TEMPLATE,
        workout_text=workout_text,
        pretty_json=pretty_json,
        error=error,
        parsed_output=parsed_output
    )
@app.route("/confirm", methods=["POST"])
def confirm():
    workout_text = request.form.get("workout_text", "")
    parsed_output = request.form.get("parsed_output", "")
    # De-serialize safely (just once)
    try:
        parsed_data = json.loads(parsed_output)
    except Exception as e:
        return f"Failed to parse data for saving: {e}", 400

    # Get logged-in user's email
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
    # Save each entry to the DB
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


app.debug = True
