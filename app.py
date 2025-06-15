import os
from dotenv import load_dotenv
from openai import OpenAI
import csv
import json
import pandas as pd 
from datetime import datetime

# Import parsing function and exercise list text from main.py
from main import parse_workout_input, exerciseListText
from main import find_best_match, tag_df
from flask import Flask, request, render_template_string

# Load your OpenAI API key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

# --------- HTML template for the simple web UI ----------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>GymLLM Workout Logger</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 700px; margin: auto; background: #fafafa; }
        h1 { color: #2d4059; }
        form { margin-bottom: 20px; }
        textarea { width: 100%; font-size: 1.1em; }
        input[type="submit"] { padding: 6px 18px; background: #247ba0; color: white; border: none; border-radius: 4px; }
        .nav { margin-bottom: 15px; }
        .nav a { color: #247ba0; text-decoration: none; margin-right: 18px; font-weight: bold; }
        .status { margin: 15px 0; padding: 10px; background: #ffe; border-left: 4px solid #fdcb6e;}
        pre { background: #f4f4f4; padding: 8px; border-radius: 4px;}
    </style>
</head>
<body>
    <div class="nav">
        <a href="/search">Search/Filter Log</a>
    </div>
    <h1>Log Your Workout</h1>
    <form method="post">
        <label for="workout">Workout:</label><br>
        <textarea id="workout" name="workout" rows="4" cols="50" placeholder="e.g. bench 185 for 5x5, lat pulldowns 3x10, etc."></textarea><br>
        <input type="submit" value="Submit">
    </form>
    {% if log_status %}
        <div class="status">{{ log_status }}</div>
    {% endif %}
    {% if submitted %}
        <h2>You submitted:</h2>
        <pre>{{ workout_text }}</pre>
        {% if parsed_output %}
            <h2>LLM Output:</h2>
            <pre>{{ parsed_output }}</pre>
        {% endif %}
    {% endif %}
</body>
</html>
"""

#html template for the searchUI tool
SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
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


@app.route("/", methods=["GET", "POST"])
def home():
    parsed_output = None      # What the LLM returns
    workout_text = ""         # What user entered
    log_status = ""           # Message to show if we logged the workout

    if request.method == "POST":
        workout_text = request.form.get("workout", "")
        # 1. Call your LLM parser from main.py
        parsed_output = parse_workout_input(workout_text, client, exerciseListText)

        # 2. Try to parse as JSON and log to CSV if possible
        try:
            parsed_data = json.loads(parsed_output)
            # parsed_data should be a list of dicts

            # Prepare CSV logging (append mode, create if not exists)
            csv_path = "workoutLog.csv"
            file_exists = os.path.exists(csv_path)
            with open(csv_path, mode="a", newline="") as file:
                writer = csv.writer(file)
                # If new file, write header
                if not file_exists:
                    writer.writerow(["date", "exercise", "weight", "sets", "reps", "notes", "tags"])
                today_str = datetime.now().strftime("%Y-%m-%d")
                
                for entry in parsed_data:
                    # Normalize exercise name and get tags using your canonical list
                    matched_name, tags = find_best_match(entry.get("exercise", ""), tag_df)
                    # Overwrite the name with the canonical one, and save tags
                    writer.writerow([
                        today_str,
                        matched_name,
                        entry.get("weight", ""),
                        entry.get("sets", ""),
                        entry.get("reps", ""),
                        entry.get("notes", ""),
                        tags
                    ])
            log_status = f"Logged {len(parsed_data)} workout(s) to CSV."
        except Exception as e:
            # Not valid JSON—probably a clarifying question or error
            log_status = "Not logged (clarifying question or invalid response)."

    # Render the HTML, passing in all variables
    return render_template_string(
        HTML_TEMPLATE,
        submitted=(request.method == "POST"),
        workout_text=workout_text,
        parsed_output=parsed_output,
        log_status=log_status
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
    

if __name__ == "__main__":
    # Start the Flask dev server on localhost:5000 with debug mode
    app.run(debug=True)
