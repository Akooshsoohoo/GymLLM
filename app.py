from flask import Flask

app = Flask(__name__)

#temporary html template
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
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    # If the form was submitted (POST request), get the text
    if request.method == "POST":
        workout_text = request.form.get("workout", "")
        # Pass the entered text back to the page
        return render_template_string(HTML_TEMPLATE, submitted=True, workout_text=workout_text)
    # If just visiting (GET), show the empty form
    return render_template_string(HTML_TEMPLATE, submitted=False)

if __name__ == "__main__":
    # Start the Flask dev server on localhost:5000 with debug mode on
    app.run(debug=True)