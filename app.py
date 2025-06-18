import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, session, request, render_template_string
from flask_dance.contrib.google import make_google_blueprint, google

import csv
import json
import pandas as pd
from datetime import datetime
from openai import OpenAI

# Import your parsing and matching functions
from main import parse_workout_input, exerciseListText, find_best_match, tag_df

# Set up OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- BEGIN CRUCIAL OAUTH FIXES --- #
# The .env should use GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET exactly as in your Google Cloud credentials.
# Also, use the correct redirect_url path: '/login/google/authorized'
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersekrit")  # Needed for sessions

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),           # <-- match .env key
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),   # <-- match .env key
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid"
    ],
    redirect_url="/login/google/authorized"            # <-- must match Google Cloud Console
)
app.register_blueprint(google_bp, url_prefix="/login")
# --- END CRUCIAL OAUTH FIXES --- #

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
</head>
<body>
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
            </tr>
            {% for i in range(rows|length) %}
            <tr>
                {% for j in range(rows[i]|length) %}
                <td>
                    <input type="text" name="cell-{{i}}-{{j}}" value="{{ rows[i][j] }}">
                </td>
                {% endfor %}
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


@app.route("/login")
def login():
    print("google.token =", google.token)
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    assert resp.ok, resp.text
    email = resp.json()["email"]
    return f"Logged in as: {email}"

@app.route("/", methods=["GET"])
def home():
    # GET only: just show the input form, do not process/log anything here
    return render_template_string(
        HTML_TEMPLATE,
        submitted=False,
        workout_text="",
        parsed_output=None,
        log_status=""
    )

@app.route("/search", methods=["GET", "POST"])
def search():
    query = request.values.get("query", "").lower()

    try:
        df = pd.read_csv("workoutLog.csv")
    except FileNotFoundError:
        df = pd.DataFrame(columns=["date", "exercise", "weight", "sets", "reps", "notes", "tags"])

    if request.method == "POST":
        # Update DataFrame with posted cell data
        num_rows = int(request.form.get("num_rows", 0))
        num_cols = int(request.form.get("num_cols", 7))
        updated_rows = []

        for i in range(num_rows):
            row = []
            for j in range(num_cols):
                val = request.form.get(f"cell-{i}-{j}", "")
                row.append(val)
            updated_rows.append(row)

        df = pd.DataFrame(updated_rows, columns=df.columns if not df.empty else ["date", "exercise", "weight", "sets", "reps", "notes", "tags"])
        df.to_csv("workoutLog.csv", index=False)

        # 🔁 Redirect to avoid form resubmission on reload
        return redirect(url_for("search", query=query))

    # Handle search filter (for both GET and after redirect)
    if query:
        df = df[df.apply(lambda row: query in row.to_string().lower(), axis=1)]

    rows = df.values.tolist()
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
    # Write to CSV (using your canonical name and tag logic)
    csv_path = "workoutLog.csv"
    file_exists = os.path.exists(csv_path)
    with open(csv_path, mode="a", newline="") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["date", "exercise", "weight", "sets", "reps", "notes", "tags"])
        today_str = datetime.now().strftime("%Y-%m-%d")
        for entry in parsed_data:
            matched_name, tags = find_best_match(entry.get("exercise", ""), tag_df)
            writer.writerow([
                today_str,
                matched_name,
                entry.get("weight", ""),
                entry.get("sets", ""),
                entry.get("reps", ""),
                entry.get("notes", ""),
                tags
            ])
    # Show a nice summary after saving
    pretty_json = json.dumps(parsed_data, indent=2)
    return render_template_string(
        SAVED_TEMPLATE,
        pretty_json=pretty_json
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


app.debug = True
