import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, session, request, render_template_string
from flask_dance.contrib.google import make_google_blueprint, google
from flask_sqlalchemy import SQLAlchemy

import csv       # still imported for other modules—safe to keep
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

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
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
# --- END  OAUTH SETUP --------------------------------------------------


# --------- HTML templates ----------

REVIEW_TEMPLATE = """ (unchanged) """

SAVED_TEMPLATE = """ (unchanged) """

HTML_TEMPLATE = """ (unchanged) """

# --- SEARCH_TEMPLATE (only the <thead>/<tbody> loops changed) ----------
SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>Search Workout Log</title>
<style>
    table { width:100%; border-collapse:collapse; margin-top:10px; }
    th,td { border:1px solid #bbb; padding:8px; text-align:left; font-size:1rem; }
    th     { background:#e0e9f3; font-weight:bold; }
    input[type="text"] { width:100%; box-sizing:border-box; font-size:1rem;
                         padding:5px 4px; border:1px solid #d2d2d2; border-radius:5px;
                         background:#f9f9fc; }
    input[type="submit"],button { margin-top:10px; padding:8px 18px; font-size:1rem;
                                  background:#2288c7; color:#fff; border:none; border-radius:6px;
                                  cursor:pointer; transition:background .15s; }
    input[type="submit"]:hover,button:hover { background:#1e6ea3; }
    body { font-family:"Segoe UI",Arial,sans-serif; }
    .nav,a { font-size:1rem; }
</style>
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
                {% for j in range(7) %}  {# only show the first 7 visible cols #}
                <td><input type="text" name="cell-{{i}}-{{j}}"
                           value="{{ rows[i][j] }}"></td>
                {% endfor %}
                <td style="text-align:center;">
                    <input type="checkbox" name="delete-{{i}}">
                </td>
            </tr>
            <!-- row ID hidden so we can edit/delete -->
            <input type="hidden" name="id-{{i}}" value="{{ rows[i][7] }}">
            {% endfor %}
        </table>

        <input type="hidden" name="num_rows" value="{{ rows|length }}">
        <input type="hidden" name="num_cols" value="7">
        <input type="submit" value="Save Changes">
    </form>
    <br>
    <a href="/">Back to Log Input</a>

    <script>
    document.addEventListener("DOMContentLoaded", () => {
        let changed=false;
        const inputs=document.querySelectorAll("form[action='/search'] input[type='text']");
        const saveBtn=document.querySelector("form[action='/search'] input[type='submit']");
        const form=document.querySelector("form[action='/search']");
        saveBtn.style.display="none";
        inputs.forEach(inp=>inp.addEventListener("input",()=>{
            if(!changed){ changed=true; saveBtn.style.display="inline-block"; }
        }));
        form.addEventListener("submit",()=>changed=false);
        window.addEventListener("beforeunload",e=>{
            if(changed){ e.preventDefault(); e.returnValue=''; }
        });
    });
    </script>
</body>
</html>
"""
# ----------------------------------------------------------------------


# --------- Routes ---------

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
    return redirect(url_for("home")) if google.authorized else redirect(url_for("google.login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/oauth_success")
def oauth_success():
    return redirect(url_for("home"))


@app.route("/", methods=["GET"])
def home():
    user_email = None
    if google.authorized:
        try:
            r = google.get("/oauth2/v2/userinfo")
            if r.ok:
                user_email = r.json().get("email")
        except Exception:
            pass
    return render_template_string(
        HTML_TEMPLATE,
        user_email=user_email,
        submitted=False, workout_text="", parsed_output=None, log_status=""
    )


@app.route("/search", methods=["GET", "POST"])
def search():
    # --- who is logged in? --------------------------------------------
    user_email = None
    if google.authorized:
        try:
            r = google.get("/oauth2/v2/userinfo")
            if r.ok:
                user_email = r.json().get("email")
        except Exception:
            pass
    if not user_email:
        return redirect(url_for("login"))

    # --- UPDATE / DELETE submitted rows -------------------------------
    if request.method == "POST":
        num_rows = int(request.form.get("num_rows", 0))

        for i in range(num_rows):
            row_id = request.form.get(f"id-{i}")
            if not row_id:
                continue
            workout = Workout.query.filter_by(id=row_id, user_email=user_email).first()
            if not workout:
                continue

            # delete?
            if request.form.get(f"delete-{i}"):
                db.session.delete(workout)
                continue

            # otherwise, update seven editable fields
            workout.date     = request.form.get(f"cell-{i}-0", "")
            workout.exercise = request.form.get(f"cell-{i}-1", "")
            workout.weight   = request.form.get(f"cell-{i}-2", "")
            workout.sets     = request.form.get(f"cell-{i}-3", "")
            workout.reps     = request.form.get(f"cell-{i}-4", "")
            workout.notes    = request.form.get(f"cell-{i}-5", "")
            workout.tags     = request.form.get(f"cell-{i}-6", "")
        db.session.commit()
        # PRG pattern – redirect so refresh won’t resubmit
        return redirect(url_for("search", query=request.args.get("query", "")))

    # --- BUILD table for GET (and after redirect) ---------------------
    query = request.values.get("query", "").lower()
    workouts = Workout.query.filter_by(user_email=user_email).all()

    if query:
        workouts = [w for w in workouts
                    if query in f"{w.date} {w.exercise} {w.tags}".lower()]

    rows = [[w.date, w.exercise, w.weight, w.sets,
             w.reps, w.notes, w.tags, w.id] for w in workouts]

    return render_template_string(SEARCH_TEMPLATE, rows=rows, query=query)


@app.route("/review", methods=["POST"])
def review():
    workout_text = request.form.get("workout", "")
    parsed_output = parse_workout_input(workout_text, client, exerciseListText)
    try:
        parsed_data = json.loads(parsed_output)
        pretty_json, error = json.dumps(parsed_data, indent=2), None
    except Exception:
        pretty_json, error = None, "Could not parse the workout. LLM responded with a question or invalid format."
    return render_template_string(REVIEW_TEMPLATE,
        workout_text=workout_text, pretty_json=pretty_json,
        error=error, parsed_output=parsed_output
    )


@app.route("/confirm", methods=["POST"])
def confirm():
    parsed_output = request.form.get("parsed_output", "")
    try:
        parsed_data = json.loads(parsed_output)
    except Exception as e:
        return f"Failed to parse data for saving: {e}", 400

    user_email = None
    if google.authorized:
        try:
            r = google.get("/oauth2/v2/userinfo")
            if r.ok:
                user_email = r.json().get("email")
        except Exception:
            pass
    if not user_email:
        return "Not logged in", 401

    today = datetime.now().strftime("%Y-%m-%d")
    for entry in parsed_data:
        name, tags = find_best_match(entry.get("exercise", ""), tag_df)
        db.session.add(
            Workout(user_email=user_email, date=today,
                    exercise=name,
                    weight=entry.get("weight", ""),
                    sets=entry.get("sets", ""),
                    reps=entry.get("reps", ""),
                    notes=entry.get("notes", ""),
                    tags=tags)
        )
    db.session.commit()
    return render_template_string(
        SAVED_TEMPLATE, pretty_json=json.dumps(parsed_data, indent=2)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
