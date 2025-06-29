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

def parse_workout_input(user_input, client, exerciseListText):
    systemPrompt = (
        "You are a workout log parser that turns natural-language gym logs into structured data. "
        # ... [unchanged, omitted for brevity] ...
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
    cleanReply = reply.removeprefix("```json").removesuffix("```").strip()
    return cleanReply

# --------- Match a raw name to a canonical name + tags ---------

def find_best_match(raw_name, tag_df, client):
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
        except:
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
