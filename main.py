from dotenv import load_dotenv
load_dotenv()  # Load .env file so we get your API key
from openai import OpenAI
import csv
import json
import os
from datetime import datetime, timedelta
import pandas as pd  # For tag matching
import re  # For extracting dates from input

# --------- Load canonical tag data and build exercise list ---------

def load_tagged_exercise_list(path="taggedExerciseList.csv"):
    df = pd.read_csv(path)
    df["exercise"] = df["exercise"].str.lower().str.strip()
    return df

tag_df = load_tagged_exercise_list()
exerciseListText = ", ".join(tag_df["exercise"].tolist())

# --------- Core Parsing Function (used in both CLI and web app) ---------

def parse_workout_input(user_input, client, exerciseListText, model="gpt-3.5-turbo"):
    systemPrompt = (
        "You are a workout log parser. Convert natural-language gym logs into structured JSON.\n\n"

        "OUTPUT: Return ONLY a raw JSON array — no markdown, no code fences, no explanation.\n"
        "Example: [{\"exercise\": \"barbell bench press\", \"weight\": \"185 lbs\", \"sets\": 3, \"reps\": [10, 10, 10], \"notes\": \"\"}]\n\n"

        "SETS & REPS — interpret shorthand as follows:\n"
        "  '5x5'        → sets: 5, reps: [5,5,5,5,5]\n"
        "  '3x10'       → sets: 3, reps: [10,10,10]\n"
        "  '4x8'        → sets: 4, reps: [8,8,8,8]\n"
        "  '10,8,6'     → sets: 3, reps: [10,8,6]\n"
        "  'sets of 12' (no count given) → assume 3 sets → sets: 3, reps: [12,12,12]\n"
        "  'a few sets' → assume 3 sets\n"
        "  only reps mentioned, no sets → assume 1 set\n"
        "  no reps or sets mentioned → omit both (leave null)\n\n"

        "WEIGHT:\n"
        "  Include units if stated ('185 lbs', '80 kg').\n"
        "  'bodyweight' or 'BW' → weight: 'bodyweight'.\n"
        "  Not mentioned → weight: ''.\n\n"

        "ASSUMPTIONS — always assume rather than ask unless truly impossible:\n"
        "  Unclear equipment → pick the most common variant (usually barbell for compounds, dumbbell for isolation).\n"
        "  Unclear weight → leave blank.\n"
        "  Unclear reps → use the most reasonable default for that exercise.\n\n"

        "EXERCISE NAMES — match to this list when possible. Only invent a name if nothing fits:\n"
        + exerciseListText + "\n\n"

        "Each JSON object must have these keys: exercise, weight, sets, reps, notes.\n"
        "sets is an integer. reps is a list of integers (one per set). All others are strings.\n"
        "Return ONLY the JSON array. Nothing else."
    )
    messages = [
        {"role": "system", "content": systemPrompt},
        {"role": "user", "content": user_input}
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages
    )
    reply = response.choices[0].message.content.strip()
    # strip code fences local models sometimes add
    cleanReply = reply.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # if the model added text before the array, extract just the JSON array
    start = cleanReply.find("[")
    end = cleanReply.rfind("]")
    if start != -1 and end != -1:
        cleanReply = cleanReply[start:end + 1]
    return cleanReply

# --------- Match a raw name to a canonical name + tags ---------

def find_best_match(raw_name, tag_df, client, model="gpt-3.5-turbo"):
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
        model=model,
        messages=[{"role": "user", "content": tag_prompt}]
    )
    generated_tags = tag_response.choices[0].message.content.strip()
    return raw_name, generated_tags

# --------- Ensure the workout log CSV exists ---------

if not os.path.exists("workoutLog.csv"):
    with open("workoutLog.csv", mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "exercise", "weight", "sets", "reps", "notes", "tags"])

# --------- Extract a date from user input text ---------

def extract_date(user_input):
    lowered = user_input.lower()
    today = datetime.now()
    if "yesterday" in lowered:
        return today - timedelta(days=1)
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, day in enumerate(weekdays):
        if day in lowered:
            today_idx = today.weekday()
            delta = (today_idx - i) % 7 or 7
            return today - timedelta(days=delta)
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", user_input)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    return today

# --------- Optional CLI mode for standalone use ---------

if __name__ == "__main__":
    # Use a locally-set key for CLI fallback (or error if not present)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment for CLI mode.")
    client = OpenAI(api_key=api_key)
    messages = [{"role": "system", "content": parse_workout_input.__doc__}]
    userInput = input("Describe your workout today: ")
    dateObj = extract_date(userInput)
    dateStr = dateObj.strftime("%Y-%m-%d")
    messages.append({"role": "user", "content": userInput})

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

    with open("workoutLog.csv", mode="a", newline="") as file:
        writer = csv.writer(file)
        for entry in parsedData:
            matched_name, tags = find_best_match(entry.get("exercise", ""), tag_df, client)
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
