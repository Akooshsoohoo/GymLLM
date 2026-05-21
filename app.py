import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, session, request, render_template_string
from flask_dance.contrib.google import make_google_blueprint, google

from flask_sqlalchemy import SQLAlchemy

import json
import pandas as pd
import openai
from datetime import datetime
from openai import OpenAI
from openai import AuthenticationError, RateLimitError
from main import parse_workout_input, exerciseListText, find_best_match, tag_df

OPENAI_MODEL = "gpt-3.5-turbo"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is not set! Aborting.")

db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL environment variable is not set! Aborting.")
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>Review & Confirm Workout</title>
</head>
<body>
    {% if user_email %}
    <div class="account-bar">
        <span class="account-email">{{ user_email }}</span>
        <a href="/logout" class="logout-btn">Logout</a>
    </div>
    {% endif %}
    <div class="nav">
        <a href="/">Log Workout</a>
        <a href="/search">Search/Filter Log</a>
        <a href="/apikey">API Key Config</a>
        {% if not user_email %}<a href="/login">Sign In</a>{% endif %}
    </div>
    <h1>Review & Confirm Workout</h1>
    {% if error %}
        <div class="status">{{ error }}</div>
    {% endif %}
    <form method="post" action="/review">
        <label for="workout">Edit your original workout prompt:</label><br>
        <textarea id="workout" name="workout" rows="4" cols="50">{{ workout_text }}</textarea><br>
        <input type="hidden" id="user_api_key" name="user_api_key" value="">
        <input type="hidden" id="llm_mode" name="llm_mode" value="">
        <input type="hidden" id="local_model" name="local_model" value="">
        <input type="submit" value="Re-Parse & Review">
    </form>
    <script>
    document.getElementById('user_api_key').value = localStorage.getItem('openai_api_key') || '';
    document.getElementById('llm_mode').value = localStorage.getItem('llm_mode') || 'openai';
    document.getElementById('local_model').value = localStorage.getItem('local_model') || 'llama3.2';
    </script>
    {% if pretty_json %}
        <h2>LLM Parsed Output:</h2>
        <pre>{{ pretty_json }}</pre>
        <form method="post" action="/confirm">
            <input type="hidden" name="workout_text" value="{{ workout_text }}">
            <input type="hidden" name="parsed_output" value="{{ parsed_output }}">
            <input type="hidden" name="llm_mode" value="{{ llm_mode }}">
            <input type="hidden" name="local_model" value="{{ local_model }}">
            <input type="hidden" name="user_api_key" value="{{ user_api_key_hidden }}">
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
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    {% if user_email %}
    <div class="account-bar">
        <span class="account-email">{{ user_email }}</span>
        <a href="/logout" class="logout-btn">Logout</a>
    </div>
    {% endif %}
    <div class="nav">
        <a href="/">Log Another</a>
        <a href="/search">Search/Filter Log</a>
        <a href="/apikey">API Key Config</a>
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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>GymLLM Workout Logger</title>
</head>
<body>
    {% if user_email %}
    <div class="account-bar">
        <span class="account-email">{{ user_email }}</span>
        <a href="/logout" class="logout-btn">Logout</a>
    </div>
    {% endif %}
    <div class="nav">
        <a href="/">Log Workout</a>
        <a href="/search">Search/Filter Log</a>
        <a href="/apikey">API Key Config</a>
        {% if not user_email %}<a href="/login">Sign In</a>{% endif %}
    </div>
    <h1>GymLLM</h1>
    <form method="post" action="/review">
        <label for="workout">Workout:</label><br>
        <textarea id="workout" name="workout" rows="4" cols="50" placeholder="e.g. bench 185 for 5x5, lat pulldowns 3x10, etc."></textarea><br>
        <input type="hidden" id="user_api_key" name="user_api_key" value="">
        <input type="hidden" id="llm_mode" name="llm_mode" value="">
        <input type="hidden" id="local_model" name="local_model" value="">
        <input type="submit" value="Submit">
    </form>
    <script>
    const key = localStorage.getItem('openai_api_key');
    const mode = localStorage.getItem('llm_mode') || 'openai';
    document.getElementById('user_api_key').value = key || '';
    document.getElementById('llm_mode').value = mode;
    document.getElementById('local_model').value = localStorage.getItem('local_model') || 'llama3.2';
    if (mode !== 'local' && !key) {
        window.location.href = "/apikey";
    }
    </script>

</body>
</html>
"""

SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<title>Search Workout Log</title>
</head>
<body>
    {% if user_email %}
    <div class="account-bar">
        <span class="account-email">{{ user_email }}</span>
        <a href="/logout" class="logout-btn">Logout</a>
    </div>
    {% endif %}
    <div class="nav">
        <a href="/">Log Workout</a>
        <a href="/search">Search/Filter Log</a>
        <a href="/apikey">API Key Config</a>
        {% if not user_email %}<a href="/login">Sign In</a>{% endif %}
    </div>
    <h1>Search Your Workout Log</h1>
    <div style="margin-bottom:16px;">
        <label for="query">Search:</label>
        <input type="text" id="query" name="query" style="width:100%;" autocomplete="off" placeholder="Filter by exercise, date, tag...">
    </div>

    <script>
    document.getElementById('query').addEventListener('input', function() {
        var q = this.value.toLowerCase();
        var rows = document.querySelectorAll('#workout-table tbody tr');
        rows.forEach(function(row) {
            var cellText = Array.from(row.querySelectorAll('input[type="text"]'))
                .map(function(i) { return i.value; })
                .join(' ')
                .toLowerCase();
            row.style.display = (q === '' || cellText.includes(q)) ? '' : 'none';
        });
    });
    </script>

    <form method="post" action="/search">
        <table id="workout-table">
            <thead>
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
            </thead>
            <tbody>
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
            </tbody>
        </table>
        <input type="hidden" name="num_rows" value="{{ rows|length }}">
        <input type="hidden" name="num_cols" value="{{ rows[0]|length if rows else 7 }}">
        <input type="submit" value="Save Changes">
    </form>
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
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            html, body {
                height: 100%;
                margin: 0;
                padding: 0;
            }
            body {
                font-family: 'Inter', sans-serif;
                background: #181824;
                color: #f4f4ff;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                overflow: hidden;
                position: relative;
            }
            .login-box {
                z-index: 2;
                text-align: center;
                background: rgba(30, 20, 54, 0.77);
                padding: 2.2rem 2.6rem 2.5rem 2.6rem;
                border-radius: 1.4rem;
                box-shadow: 0 8px 32px #00000040;
                backdrop-filter: blur(3px);
            }
            h1 {
                font-size: 3.1rem;
                font-family: 'Inter', sans-serif;
                letter-spacing: 1px;
                color: #b48eff;
                margin-bottom: 0.4rem;
                font-weight: 700;
            }
            .login-box p {
                font-size: 1.29rem;
                margin-bottom: 1.6rem;
                color: #dfd3ff;
                opacity: 0.9;
                font-family: 'Inter', sans-serif;
            }
            .login-button {
                padding: 12px 32px;
                background: linear-gradient(90deg, #7f5af0, #b48eff 96%);
                border: none;
                color: white;
                font-size: 1.18rem;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                letter-spacing: 0.6px;
                transition: background 0.3s;
                box-shadow: 0 2px 16px #7f5af022;
                font-family: 'Inter', sans-serif;
            }
            .login-button:hover {
                background: linear-gradient(90deg, #6847d2 70%, #b48eff 100%);
            }
            .welcome-bg {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                z-index: 0;
                pointer-events: none;
            }
        </style>
    </head>
    <body>
        <div class="welcome-bg">
            <svg width="100vw" height="100vh" style="position:absolute;top:0;left:0;" xmlns="http://www.w3.org/2000/svg">
                <defs>
                  <radialGradient id="grad1" cx="50%" cy="50%" r="70%">
                    <stop offset="0%" stop-color="#7f5af099"/>
                    <stop offset="100%" stop-color="transparent"/>
                  </radialGradient>
                  <radialGradient id="grad2" cx="80%" cy="25%" r="50%">
                    <stop offset="0%" stop-color="#b48eff88"/>
                    <stop offset="100%" stop-color="transparent"/>
                  </radialGradient>
                </defs>
                <ellipse id="blob1" cx="22%" cy="55%" rx="220" ry="140" fill="url(#grad1)">
                  <animate attributeName="cx" values="22%;32%;22%" dur="16s" repeatCount="indefinite"/>
                  <animate attributeName="cy" values="55%;62%;55%" dur="19s" repeatCount="indefinite"/>
                </ellipse>
                <ellipse id="blob2" cx="75%" cy="25%" rx="130" ry="110" fill="url(#grad2)">
                  <animate attributeName="cx" values="75%;70%;75%" dur="17s" repeatCount="indefinite"/>
                  <animate attributeName="cy" values="25%;35%;25%" dur="22s" repeatCount="indefinite"/>
                </ellipse>
            </svg>
        </div>
        <div class="login-box">
            <h1>GymLLM</h1>
            <p>Log your workouts with simple, natural language.</p>
            <a href="/login"><button class="login-button">Log in with Google</button></a>
        </div>
    </body>
    </html>
    """)




def get_user_email():
    """Return the signed-in user's email, or None. Clears an expired token so the
    next request properly redirects to login instead of silently showing no account bar."""
    if not google.authorized:
        return None
    try:
        resp = google.get("/oauth2/v2/userinfo")
        if resp.ok:
            return resp.json().get("email")
        if resp.status_code in (401, 403):
            del google_bp.token
    except Exception:
        pass
    return None


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

@app.route("/apikey", methods=["GET"])
def apikey_config():
    user_email = get_user_email()
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Configure API Key | GymLLM</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
        <style>
            .disabled { opacity: 0.5; cursor: not-allowed !important; }
            #status-box {
                margin-top: 18px;
                display: none;
                background: #2a2035;
                border-left: 6px solid #b48eff;
                border-radius: 5px;
                color: #dfd3ff;
                padding: 13px 18px;
                font-size: 1.08em;
                font-weight: 500;
                max-width: 560px;
            }
            .step-list li { margin-bottom: 0.7em; }
            #apikey { letter-spacing: 0.04em; }
        </style>
    </head>
    <body>
        {% if user_email %}
        <div class="account-bar">
            <span class="account-email">{{ user_email }}</span>
            <a href="/logout" class="logout-btn">Logout</a>
        </div>
        {% endif %}
        <div class="nav" id="nav" style="display:none;">
            <a href="/" id="log-link">Log Workout</a>
            <a href="/search" id="search-link">Search/Filter Log</a>
        </div>
        <h1>Configure LLM</h1>

        <div style="display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap;">
            <button id="tab-openai" onclick="showTab('openai')" style="flex:1;min-width:140px;padding:10px 0;font-size:1rem;border-radius:8px;border:2px solid #7f5af0;background:#2a2035;color:#d4bfff;cursor:pointer;font-weight:600;">OpenAI API Key</button>
            <button id="tab-local" onclick="showTab('local')" style="flex:1;min-width:140px;padding:10px 0;font-size:1rem;border-radius:8px;border:2px solid #444;background:#1e1e2e;color:#aaa;cursor:pointer;font-weight:600;">Local LLM (Ollama)</button>
        </div>

        <div id="panel-openai">
            <ol class="step-list">
                <li>Go to <a href="https://platform.openai.com/api-keys" target="_blank" style="color:#b48eff;font-weight:600;">openai.com/api-keys</a></li>
                <li>Click <b>+ Create new secret key</b>, name it <b>GymLLM</b>, click <b>Create</b></li>
                <li>Copy the key (starts with <b>sk-</b>) and paste it below</li>
            </ol>
            <input type="text" id="apikey" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Paste your OpenAI API key (starts with sk-)" style="width:100%; max-width:480px;"/>
            <button id="savekey" class="disabled" disabled>Save</button>
        </div>

        <div id="panel-local" style="display:none;">
            <ol class="step-list">
                <li>Install <a href="https://ollama.com" target="_blank" style="color:#b48eff;font-weight:600;">Ollama</a> on your machine</li>
                <li>Pull a model, e.g. <code style="background:#2a2035;padding:2px 6px;border-radius:4px;">ollama pull llama3.2</code></li>
                <li>Make sure Ollama is running, then click <b>Use Local LLM</b> below</li>
            </ol>
            <label style="display:block;margin-bottom:6px;">Model name:</label>
            <input type="text" id="local-model-input" autocomplete="off" placeholder="e.g. llama3.2, mistral, phi3" style="width:100%; max-width:280px;" value="llama3.2"/>
            <button id="save-local" style="margin-left:8px;">Use Local LLM</button>
        </div>

        <div id="status-box"></div>
        <script>
        function validKey(k) {
            return /^sk-[A-Za-z0-9\\-._]{20,}$/.test(k.trim());
        }
        function showNav() {
            document.getElementById('nav').style.display = 'block';
        }
        function showStatus(msg, color, border) {
            var s = document.getElementById('status-box');
            s.style.display = 'block';
            s.style.color = color;
            s.style.borderLeft = '6px solid ' + border;
            s.innerHTML = msg;
        }
        function showTab(tab) {
            document.getElementById('panel-openai').style.display = tab === 'openai' ? '' : 'none';
            document.getElementById('panel-local').style.display = tab === 'local' ? '' : 'none';
            document.getElementById('tab-openai').style.borderColor = tab === 'openai' ? '#7f5af0' : '#444';
            document.getElementById('tab-openai').style.color = tab === 'openai' ? '#d4bfff' : '#aaa';
            document.getElementById('tab-openai').style.background = tab === 'openai' ? '#2a2035' : '#1e1e2e';
            document.getElementById('tab-local').style.borderColor = tab === 'local' ? '#7f5af0' : '#444';
            document.getElementById('tab-local').style.color = tab === 'local' ? '#d4bfff' : '#aaa';
            document.getElementById('tab-local').style.background = tab === 'local' ? '#2a2035' : '#1e1e2e';
            document.getElementById('status-box').style.display = 'none';
        }
        window.addEventListener('DOMContentLoaded', function() {
            var mode = localStorage.getItem('llm_mode');
            if (mode === 'local') {
                showTab('local');
                var m = localStorage.getItem('local_model') || 'llama3.2';
                document.getElementById('local-model-input').value = m;
                showNav();
                showStatus("✅ Using local LLM (<b>" + m + "</b>). <b>Click Log Workout to start.</b>", "#c1ffd1", "#41d174");
            } else {
                var key = localStorage.getItem('openai_api_key');
                if (key && validKey(key)) {
                    showNav();
                    showStatus("✅ You're good to go! <b>Click Log Workout to start.</b>", "#c1ffd1", "#41d174");
                }
            }
        });
        document.getElementById('apikey').addEventListener('input', function() {
            var key = this.value.trim();
            var btn = document.getElementById('savekey');
            if (validKey(key)) {
                btn.disabled = false;
                btn.classList.remove('disabled');
                document.getElementById('status-box').style.display = 'none';
            } else {
                btn.disabled = true;
                btn.classList.add('disabled');
                if (key.length > 0) {
                    showStatus("❌ Invalid API key. Must start with <b>sk-</b> and be at least 48 characters.", "#ffd1d1", "#e64b4b");
                } else {
                    document.getElementById('status-box').style.display = 'none';
                }
            }
        });
        document.getElementById('savekey').onclick = function() {
            var key = document.getElementById('apikey').value.trim();
            if (!validKey(key)) {
                showStatus("❌ Invalid API key. Must start with <b>sk-</b> and be at least 48 characters.", "#ffd1d1", "#e64b4b");
                return;
            }
            localStorage.setItem('openai_api_key', key);
            localStorage.setItem('llm_mode', 'openai');
            showStatus("✅ API key saved! <b>You're good to go. Click Log Workout to start.</b>", "#c1ffd1", "#41d174");
            showNav();
        };
        document.getElementById('save-local').onclick = function() {
            var m = document.getElementById('local-model-input').value.trim() || 'llama3.2';
            localStorage.setItem('llm_mode', 'local');
            localStorage.setItem('local_model', m);
            localStorage.removeItem('openai_api_key');
            showStatus("✅ Local LLM set to <b>" + m + "</b>. Make sure Ollama is running, then <b>click Log Workout</b>.", "#c1ffd1", "#41d174");
            showNav();
        };
        </script>
        <p style="margin-top: 28px; color:#aaa; font-size:0.98em;">
            <strong>Privacy:</strong> Your API key is stored only in your browser and never sent to our server.
        </p>
    </body>
    </html>
    """, user_email=user_email)




@app.route("/", methods=["GET"])
def home():
    if not google.authorized:
        return redirect(url_for("welcome"))

    user_email = get_user_email()
    if not user_email:
        return redirect(url_for("welcome"))

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
    user_email = get_user_email()
    if not user_email:
        return redirect(url_for("login"))

    workouts = Workout.query.filter_by(user_email=user_email).all()
    rows = [
        [w.date, w.exercise, w.weight, w.sets, w.reps, w.notes, w.tags]
        for w in workouts
    ]

    if request.method == "POST":
        try:
            num_rows = int(request.form.get("num_rows", 0))
            num_cols = int(request.form.get("num_cols", 7))
        except ValueError:
            return "Invalid form data", 400
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
        ids_to_delete_set = set(ids_to_delete)
        for idx in sorted(ids_to_delete, reverse=True):
            db.session.delete(workouts[idx])
        db.session.commit()
        remaining = [w for i, w in enumerate(workouts) if i not in ids_to_delete_set]
        for w, row in zip(remaining, new_data):
            w.date, w.exercise, w.weight, w.sets, w.reps, w.notes, w.tags = row
        db.session.commit()
        return redirect(url_for("search"))

    # ADD user_email=user_email
    return render_template_string(SEARCH_TEMPLATE, rows=rows, user_email=user_email)

@app.route("/review", methods=["POST"])
def review():
    workout_text = request.form.get("workout", "")
    user_api_key = request.form.get("user_api_key", "").strip()
    llm_mode = request.form.get("llm_mode", "openai")
    local_model = request.form.get("local_model", "llama3.2").strip() or "llama3.2"

    pretty_json = None
    parsed_output = None
    error = None
    client = None
    model = None

    if llm_mode == "local":
        client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        model = local_model
    else:
        if not user_api_key or not user_api_key.startswith("sk-"):
            error = "OpenAI API key is missing or invalid. Please re-enter it on the API Key Config page."
        else:
            client = OpenAI(api_key=user_api_key)
            model = OPENAI_MODEL

    if client and not error:
        try:
            parsed_output = parse_workout_input(workout_text, client, exerciseListText, model=model)
            parsed_data = json.loads(parsed_output)
            pretty_json = json.dumps(parsed_data, indent=2)
        except AuthenticationError:
            error = (
                "Your OpenAI API key looks invalid or revoked. "
                "Head back to <b>API Key Config</b>, paste a fresh key, and re-try."
            )
        except RateLimitError:
            error = (
                "OpenAI is rate-limiting you or you're out of credits. "
                "Give it a minute or check your usage dashboard."
            )
        except Exception as e:
            error_detail = str(e) if not hasattr(e, 'message') else str(e.message)
            if llm_mode == "local" and ("connection" in error_detail.lower() or "refused" in error_detail.lower()):
                error = (
                    "Could not reach Ollama. Make sure it's running locally "
                    f"(<code>ollama run {local_model}</code>) and try again."
                )
            else:
                error = (
                    "Could not parse the workout or there was a problem communicating with the LLM. "
                    f"Details: {error_detail}"
                )

    user_email = get_user_email()

    return render_template_string(
        REVIEW_TEMPLATE,
        workout_text=workout_text,
        pretty_json=pretty_json,
        error=error,
        parsed_output=parsed_output,
        user_email=user_email,
        llm_mode=llm_mode,
        local_model=local_model,
        user_api_key_hidden=user_api_key,
    )



@app.route("/confirm", methods=["POST"])
def confirm():
    workout_text = request.form.get("workout_text", "")
    parsed_output = request.form.get("parsed_output", "")
    llm_mode = request.form.get("llm_mode", "openai")
    local_model = request.form.get("local_model", "llama3.2").strip() or "llama3.2"
    user_api_key = request.form.get("user_api_key", "").strip()

    try:
        parsed_data = json.loads(parsed_output)
    except Exception as e:
        return f"Failed to parse data for saving: {e}", 400

    if llm_mode == "local":
        llm_client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        model = local_model
    elif user_api_key.startswith("sk-"):
        llm_client = OpenAI(api_key=user_api_key)
        model = OPENAI_MODEL
    else:
        llm_client = None
        model = OPENAI_MODEL

    user_email = get_user_email()
    if not user_email:
        return "Not logged in", 401
    today_str = datetime.now().strftime("%Y-%m-%d")
    for entry in parsed_data:
        if llm_client:
            try:
                matched_name, tags = find_best_match(entry.get("exercise", ""), tag_df, llm_client, model=model)
            except Exception:
                matched_name, tags = entry.get("exercise", ""), ""
        else:
            matched_name, tags = entry.get("exercise", ""), ""
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
        pretty_json=pretty_json,
        user_email=user_email  
    )

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
