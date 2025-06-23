import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, session, request, render_template_string
from flask_dance.contrib.google import make_google_blueprint, google

from flask_sqlalchemy import SQLAlchemy

import json
import pandas as pd
from datetime import datetime
from openai import OpenAI

from main import parse_workout_input, exerciseListText, find_best_match, tag_df

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
    redirect_to="oauth_success",
)
app.register_blueprint(google_bp, url_prefix="/login")

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
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { border: 1px solid #bbb; padding: 8px; text-align: left; font-size: 1rem; }
    th { background: #e0e9f3; font-weight: bold; }
    input[type="text"] { width: 100%; box-sizing: border-box; font-size: 1rem; padding: 5px 4px; border: 1px solid #d2d2d2; border-radius: 5px; background: #f9f9fc; }
    input[type="submit"], button { margin-top: 10px; padding: 8px 18px; font-size: 1rem; background: #2288c7; color: #fff; border: none; border-radius: 6px; cursor: pointer; transition: background 0.15s; }
    input[type="submit"]:hover, button:hover { background: #1e6ea3; }
    body { font-family: "Segoe UI", Arial, sans-serif; }
    .nav, a { font-size: 1rem; }
</style>
</head>
<body>
    <h1>Search Your Workout Log</h1>
    <!-- Live search bar (not a form) -->
    <label for="query">Search:</label>
    <input type="text" id="query" name="query" style="width:60%;" autocomplete="off">

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
                    {%- set col_name = ['date', 'exercise', 'weight', 'sets', 'reps', 'notes', 'tags'][j] -%}
                    <input type="text" name="cell-{{i}}-{{j}}" value="{{ rows[i][j] }}"
                        {% if col_name in ['weight', 'sets', 'reps'] %}class="numonly" {% elif col_name == 'date' %}class="dateonly"{% endif %}>
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
            // Show save button if text or checkbox changes
            const inputs = document.querySelectorAll("form[action='/search'] input[type='text'], form[action='/search'] input[type='checkbox']");
            const saveButton = document.querySelector("form[action='/search'] input[type='submit']");
            const form = document.querySelector("form[action='/search']");
            saveButton.style.display = "none";
            inputs.forEach(input => {
                input.addEventListener("input", () => {
                    if (!changed) {
                        changed = true;
                        saveButton.style.display = "inline-block";
                    }
                });
            });
            form.addEventListener("submit", () => { changed = false; });
            window.addEventListener("beforeunload", function (e) {
                if (changed) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });

            // Live search filtering (matches like Ctrl+F)
            const searchInput = document.getElementById("query");
            if (searchInput) {
                searchInput.addEventListener("input", function() {
                    const filter = searchInput.value.toLowerCase().trim();
                    document.querySelectorAll("table tr").forEach((row, i) => {
                        if (i === 0) return; // skip header row
                        // Match against ALL input values in the row
                        const combined = Array.from(row.querySelectorAll("input[type='text']"))
                            .map(inp => (inp.value || inp.textContent || "").toLowerCase()).join(" ");
                        row.style.display = combined.includes(filter) ? "" : "none";
                    });
                });
            }

            // Restrict input for numeric-only columns
            document.querySelectorAll('.numonly').forEach(input => {
                input.addEventListener('input', function() {
                    // Allow digits, commas, spaces, lowercase x, periods
                    this.value = this.value.replace(/[^0-9, .x]/gi, '');
                });
            });
            // Restrict input for date columns (YYYY-MM-DD)
            document.querySelectorAll('.dateonly').forEach(input => {
                input.addEventListener('input', function() {
                    this.value = this.value.replace(/[^0-9-]/g, '');
                });
            });
        });
    </script>
</body>
</html>
"""


# --- ROUTES ---

@app.route("/welcome")
def welcome():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>GymLLM | Welcome</title>
        <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
        <style>
            body {
                margin: 0;
                background: linear-gradient(120deg, #1f1f2e, #181824);
                color: white;
                font-family: 'Segoe UI', sans-serif;
                height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                overflow: hidden;
                position: relative;
            }
            h1 {
                font-size: 3rem;
                margin-bottom: 0.5rem;
            }
            .login-box {
                z-index: 1;
                text-align: center;
            }
            .login-box p {
                font-size: 1.25rem;
                margin-bottom: 1.5rem;
            }
            .login-button {
                padding: 12px 28px;
                background: #7f5af0;
                border: none;
                color: white;
                font-size: 1.1rem;
                border-radius: 6px;
                cursor: pointer;
                transition: background 0.3s ease;
            }
            .login-button:hover {
                background: #6847d2;
            }
            .bg-animation {
                position: absolute;
                top: 0; left: 0;
                width: 100%;
                height: 100%;
                background: radial-gradient(#7f5af033 1px, transparent 1px);
                background-size: 40px 40px;
                animation: drift 20s linear infinite;
                opacity: 0.1;
            }
            @keyframes drift {
                from { background-position: 0 0; }
                to { background-position: 1000px 1000px; }
            }
        </style>
    </head>
    <body>
        <div class="bg-animation"></div>
        <div class="login-box">
            <h1>GymLLM</h1>
            <p>Log your workouts. Just type it.</p>
            <a href="/login"><button class="login-button">Log in with Google</button></a>
        </div>
    </body>
    </html>
    """)


@app.before_request
def _fix_google_token_expires():
    token = google_bp.token
    if token and "expires_in" in token and not isinstance(token["expires_in"], int):
        try:
            token["expires_in"] = int(float(token["expires_in"]))
        except (ValueError, TypeError):
            token["expires_in"] = 0
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
    # Log out of Google, then redirect back to home
    return redirect("https://accounts.google.com/Logout?continue=https://appengine.google.com/_ah/logout?continue=" + url_for("home", _external=True))


@app.route("/oauth_success")
def oauth_success():
    return redirect(url_for("home"))

@app.route("/", methods=["GET"])
def home():
    if not google.authorized:
        return redirect(url_for("welcome"))

    user_email = None
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

    # No more query filtering—just send all workouts
    workouts = Workout.query.filter_by(user_email=user_email).all()
    rows = [
        [w.date, w.exercise, w.weight, w.sets, w.reps, w.notes, w.tags]
        for w in workouts
    ]

    if request.method == "POST":
        num_rows = int(request.form.get("num_rows", 0))
        num_cols = int(request.form.get("num_cols", 7))
        new_data = []
        ids_to_delete = []
        for i in range(num_rows):
            row = []
            for j in range(num_cols):
                row.append(request.form.get(f"cell-{i}-{j}", ""))
            if request.form.get(f"delete-{i}"):
                ids_to_delete.append(i)
            else:
                new_data.append(row)
        for idx in sorted(ids_to_delete, reverse=True):
            w = workouts[idx]
            db.session.delete(w)
        db.session.commit()
        for idx, row in enumerate(new_data):
            w = workouts[idx]
            w.date, w.exercise, w.weight, w.sets, w.reps, w.notes, w.tags = row
        db.session.commit()
        return redirect(url_for("search"))

    return render_template_string(SEARCH_TEMPLATE, rows=rows)

@app.route("/review", methods=["POST"])
def review():
    workout_text = request.form.get("workout", "")
    parsed_output = parse_workout_input(workout_text, client, exerciseListText)
    try:
        parsed_data = json.loads(parsed_output)
        pretty_json = json.dumps(parsed_data, indent=2)
        error = None
    except Exception:
        pretty_json = None
        # Show the actual model output if it's a question or short text
        if parsed_output and "?" in parsed_output and len(parsed_output) < 150:
            error = f"LLM responded with: {parsed_output}"
    else:
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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

app.debug = True
