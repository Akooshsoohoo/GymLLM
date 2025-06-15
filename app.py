import os
from dotenv import load_dotenv
from openai import OpenAI
import csv
import json
import pandas as pd 
from datetime import datetime

# Import parsing and matching functions from your main.py
from main import parse_workout_input, exerciseListText
from main import find_best_match, tag_df
from flask import Flask, request, render_template_string

# Load your OpenAI API key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

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
    <h1>Log Your Workout</h1>
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
</head>
<body>
    <h1>Search Your Workout Log</h1>
    <form method="get">
        <label for="query">Search (name or tag):</label>
        <input type="text" id="query" name="query" value="{{ query|default('') }}">
        <input type="submit" value="Search">
    </form>
    <br>
    <table border="1">
        <tr>
            <th>Date</th>
            <th>Exercise</th>
            <th>Weight</th>
            <th>Sets</th>
            <th>Reps</th>
            <th>Notes</th>
            <th>Tags</th>
        </tr>
        {% for row in rows %}
        <tr>
            {% for item in row %}
            <td>{{ item }}</td>
            {% endfor %}
        </tr>
        {% endfor %}
    </table>
    <br>
    <a href="/">Back to Log Input</a>
</body>
</html>
"""

# --------- Routes ---------

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

@app.route("/search", methods=["GET"])
def search():
    # Get the query from the search form
    query = request.args.get("query", "").lower()
    try:
        df = pd.read_csv("workoutLog.csv")
    except FileNotFoundError:
        df = pd.DataFrame(columns=["date", "exercise", "weight", "sets", "reps", "notes", "tags"])
    # If a query is given, filter the DataFrame
    if query:
        df = df[df.apply(lambda row: query in row.to_string().lower(), axis=1)]
    # Convert DataFrame to list of rows
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
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <h1>Workout Saved!</h1>
        <a href="/">Log Another</a> | <a href="/search">Search Log</a>
    </body>
    </html>
    """

if __name__ == "__main__":
    # Start the Flask dev server on localhost:5000 with debug mode
    app.run(debug=True)
