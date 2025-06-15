import os
from dotenv import load_dotenv
from openai import OpenAI
import csv
import json
from datetime import datetime

# Import parsing function and exercise list text from main.py
from main import parse_workout_input, exerciseListText
from flask import Flask, request, render_template_string

# Load your OpenAI API key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

# --------- HTML template for your simple web UI ----------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>GymLLM Workout Logger</title>
</head>
<body>
    <h1>Log Your Workout</h1>
    <form method="post">
        <label for="workout">Workout:</label><br>
        <textarea id="workout" name="workout" rows="4" cols="50"></textarea><br>
        <input type="submit" value="Submit">
    </form>
    {% if submitted %}
        <h2>You submitted:</h2>
        <pre>{{ workout_text }}</pre>
        {% if parsed_output %}
            <h2>LLM Output:</h2>
            <pre>{{ parsed_output }}</pre>
        {% endif %}
        {% if log_status %}
            <h3>{{ log_status }}</h3>
        {% endif %}
    {% endif %}
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
                    writer.writerow([
                        today_str,
                        entry.get("exercise", ""),
                        entry.get("weight", ""),
                        entry.get("sets", ""),
                        entry.get("reps", ""),
                        entry.get("notes", ""),
                        ""  # tags will be added in a future step
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

if __name__ == "__main__":
    # Start the Flask dev server on localhost:5000 with debug mode
    app.run(debug=True)
