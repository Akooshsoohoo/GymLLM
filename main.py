from dotenv import load_dotenv
load_dotenv()  # Load .env file so we get your API key
from openai import OpenAI
import csv
import json
import os
from datetime import datetime, timedelta
import pandas as pd  # For tag matching
import re  # For extracting dates from input

# --------- Core Parsing Function (reusable by web app) ---------
def parse_workout_input(user_input, client, exerciseListText):
    """
    Given user_input (str), OpenAI client, and exerciseListText,
    send to LLM and return its raw reply (JSON or clarifying question).
    """
    systemPrompt = (
        "You are a workout log parser that turns natural-language gym logs into structured data. "
        "Your job is to extract clean, structured JSON data from messy, casual user input describing their workouts. "
        "Each workout entry must be returned as a flat list of JSON objects. Each object should contain:\n"
        "- exercise (must match one from the list below unless absolutely necessary to invent)\n"
        "- weight (can include units like lbs or kg, or be left blank)\n"
        "- sets (as an integer)\n"
        "- reps (as a list of integers)\n"
        "- notes (optional text for anything extra)\n\n"
        "You must **only use the following official exercise names** if they are reasonably close. "
        "Only invent a new exercise name if **no listed name is remotely appropriate**:\n"
        + exerciseListText + "\n\n"
        "When interpreting exercises:\n"
        "- Respect all equipment details. If the user says 'machine', do not substitute in a dumbbell or barbell variant.\n"
        "- Match even loose or fuzzy names (e.g. 'tri pushdown' → 'cable triceps pushdown (rope)') if equipment and intent are clear.\n"
        "- If you cannot determine which variant the user meant (e.g. dumbbell vs barbell), ask a clarifying question.\n\n"
        "If anything is vague or incomplete, respond with a brief, precise clarifying question **instead of** JSON. "
        "Examples:\n"
        "- \"Did you mean barbell or dumbbell bench press?\"\n"
        "- \"How many reps did you do for the last set, or should I leave it blank?\"\n"
        "- \"Did you mean cable machine or dumbbells for flys?\"\n\n"
        "Output rules:\n"
        "- Always return a flat JSON *list* of objects, not a dictionary or nested structure.\n"
        "- No extra commentary, just pure JSON unless clarification is needed.\n"
    )
    messages = [
        {"role": "system", "content": systemPrompt},
        {"role": "user", "content": user_input}
    ]
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    reply = response.choices[0].message.content.strip()
    # Remove extra markdown markers, if any
    cleanReply = reply.removeprefix("```json").removesuffix("```").strip()
    return cleanReply

# --------- Data Loading and Utility Functions ---------

# Make sure workoutLog.csv exists and has correct headers
if not os.path.exists("workoutLog.csv"):
    with open("workoutLog.csv", mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "exercise", "weight", "sets", "reps", "notes", "tags"])

# Load valid exercises from your canonical CSV
with open("exerciseList.csv", newline="") as exerciseFile:
    validExercises = [line.strip().lower() for line in exerciseFile if line.strip()]
    # Remove whitespace and make lowercase for easier matching
exerciseListText = ", ".join(validExercises)  # Turn list into one big string for prompt

# Load canonical tag data from CSV
def load_tagged_exercise_list(path="taggedExerciseList.csv"):
    df = pd.read_csv(path)
    df["exercise"] = df["exercise"].str.lower().str.strip()
    return df

# Match a raw name to a canonical name + tags
def find_best_match(raw_name, tag_df):
    raw = raw_name.lower().strip()
    for i, canonical in enumerate(tag_df["exercise"]):
        if raw in canonical or canonical in raw:
            return tag_df.iloc[i]["exercise"], tag_df.iloc[i]["tags"]
    # If no close match, generate tags using the LLM
    tag_prompt = (
        f"Assign descriptive muscle group and movement-type tags for the exercise: '{raw_name}'. "
        "Respond only with a semicolon-separated list of lowercase tags. "
        "Examples: 'back;pull;compound;lats', 'chest;push;isolation', 'quads;legs;compound;lower'."
    )
    tag_response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": tag_prompt}]
    )
    generated_tags = tag_response.choices[0].message.content.strip()
    return raw_name, generated_tags

# Pre-load the tags DataFrame so it doesn't reload every time
tag_df = load_tagged_exercise_list()

# Date extraction logic for flexible user input
def extract_date(user_input):
    lowered = user_input.lower()
    today = datetime.now()

    # Case: user says "yesterday"
    if "yesterday" in lowered:
        return today - timedelta(days=1)

    # Case: user gives weekday name
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, day in enumerate(weekdays):
        if day in lowered:
            today_idx = today.weekday()
            delta = (today_idx - i) % 7 or 7
            return today - timedelta(days=delta)

    # Case: explicit YYYY-MM-DD in text
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", user_input)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
        except:
            pass

    # Default: today
    return today

# Set up OpenAI client (used in CLI mode below)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --------- CLI Mode (ONLY runs when you run main.py directly) ---------
if __name__ == "__main__":
    # This code block will NOT run when main.py is imported from Flask!
    # It will ONLY run when you do `python main.py` directly.

    # Compose system prompt for the CLI mode
    systemPrompt = (
        "You are a workout log parser that turns natural-language gym logs into structured data. "
        "Your job is to extract clean, structured JSON data from messy, casual user input describing their workouts. "
        "Each workout entry must be returned as a flat list of JSON objects. Each object should contain:\n"
        "- exercise (must match one from the list below unless absolutely necessary to invent)\n"
        "- weight (can include units like lbs or kg, or be left blank)\n"
        "- sets (as an integer)\n"
        "- reps (as a list of integers)\n"
        "- notes (optional text for anything extra)\n\n"
        "You must **only use the following official exercise names** if they are reasonably close. "
        "Only invent a new exercise name if **no listed name is remotely appropriate**:\n"
        + exerciseListText + "\n\n"
        "When interpreting exercises:\n"
        "- Respect all equipment details. If the user says 'machine', do not substitute in a dumbbell or barbell variant.\n"
        "- Match even loose or fuzzy names (e.g. 'tri pushdown' → 'cable triceps pushdown (rope)') if equipment and intent are clear.\n"
        "- If you cannot determine which variant the user meant (e.g. dumbbell vs barbell), ask a clarifying question.\n\n"
        "If anything is vague or incomplete, respond with a brief, precise clarifying question **instead of** JSON. "
        "Examples:\n"
        "- \"Did you mean barbell or dumbbell bench press?\"\n"
        "- \"How many reps did you do for the last set, or should I leave it blank?\"\n"
        "- \"Did you mean cable machine or dumbbells for flys?\"\n\n"
        "Output rules:\n"
        "- Always return a flat JSON *list* of objects, not a dictionary or nested structure.\n"
        "- No extra commentary, just pure JSON unless clarification is needed.\n"
    )

    # Set up conversation
    messages = [{"role": "system", "content": systemPrompt}]

    # Prompt user for input in CLI
    userInput = input("Describe your workout today: ")
    dateObj = extract_date(userInput)
    dateStr = dateObj.strftime("%Y-%m-%d")
    messages.append({"role": "user", "content": userInput})

    # Loop until valid JSON is received from LLM
    while True:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )

        reply = response.choices[0].message.content.strip()
        print("\nGPT Response:\n")
        print(reply)

        try:
            cleanReply = reply.removeprefix("```json").removesuffix("```").strip()
            parsedData = json.loads(cleanReply)
            break
        except json.JSONDecodeError:
            clarification = input("\nClarify: ")
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": clarification})

    # Log structured workout data to CSV
    with open("workoutLog.csv", mode="a", newline="") as file:
        writer = csv.writer(file)
        for entry in parsedData:
            matched_name, tags = find_best_match(entry.get("exercise", ""), tag_df)
            entry["exercise"] = matched_name
            entry["tags"] = tags

            writer.writerow([
                dateStr,
                entry.get("exercise", ""),
                entry.get("weight", ""),
                entry.get("sets", ""),
                entry.get("reps", ""),
                entry.get("notes", ""),
                entry.get("tags", "")
            ])
