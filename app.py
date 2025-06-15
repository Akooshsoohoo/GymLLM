import os
from dotenv import load_dotenv
from openai import OpenAI

# Import parsing function from main.py
from main import parse_workout_input, exerciseListText
from flask import Flask, request, render_template_string

# Set up OpenAI like in main
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

#html template
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
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    parsed_output = None  # Will hold the result from the LLM
    workout_text = ""

    if request.method == "POST":
        workout_text = request.form.get("workout", "")
        # Call your LLM parser function!
        parsed_output = parse_workout_input(workout_text, client, exerciseListText)

    return render_template_string(HTML_TEMPLATE,
                                  submitted=(request.method == "POST"),
                                  workout_text=workout_text,
                                  parsed_output=parsed_output)
    

if __name__ == "__main__":
    # Start the Flask dev server on localhost:5000 with debug mode on
    app.run(debug=True)