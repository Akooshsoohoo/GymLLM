from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
import csv
import json
import os
from datetime import datetime
import pandas as pd  # needed for tag matching

# Ensure workoutLog.csv exists with correct headers
if not os.path.exists("workoutLog.csv"):
    with open("workoutLog.csv", mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "exercise", "weight", "sets", "reps", "notes", "tags"])

# Load valid exercises
#with open // opens the file, reads each line, then closes
with open("exerciseList.csv", newline="") as exerciseFile:  # as exerciseFile is a temp variable for this with statement
    validExercises = [line.strip().lower() for line in exerciseFile if line.strip()]
                          # line.strip removes whitespace
                          # .lower converts to lowercase
exerciseListText = ", ".join(validExercises)
        # takes the list "validExercises" and converts it into a single string
        # each exercise separated by a comma and space
        # .join just combines it all into one string, one big "   "

# Load canonical tag data
def load_tagged_exercise_list(path="taggedExerciseList.csv"):
    df = pd.read_csv(path)
    df["exercise"] = df["exercise"].str.lower().str.strip()
    return df

# Match any raw name to a canonical name + tag
def find_best_match(raw_name, tag_df):
    raw = raw_name.lower().strip()
    for i, canonical in enumerate(tag_df["exercise"]):
        if raw in canonical or canonical in raw:
            return tag_df.iloc[i]["exercise"], tag_df.iloc[i]["tags"]
    return raw_name, ""  # fallback

tag_df = load_tagged_exercise_list()

# Set up OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# System prompt with clarification logic
systemPrompt = (
    "You are a workout log parser. "
    "Given a casual workout description, return a JSON list of exercises with: "
    "exercise, weight, sets, reps (as a list), and optional notes. "
    "Use one of the following official exercise names if any are reasonably close. "
    "Only invent a new name if none of them are applicable:\n"
    + exerciseListText + "\n\n"
    "If any part of the workout log is unclear (e.g. vague exercise name, missing reps, unspecified equipment), "
    "respond with a clarifying question instead of JSON. "
    "Examples of clarifying questions: "
    "\"Did you mean barbell or dumbbell bench press?\" "
    "\"Do you remember how many reps you did, or should I leave that blank?\" "
    "Always return a flat JSON *list*, not an object with a key like 'exercises'."
)

# Loop until we get valid JSON
messages = [{"role": "system", "content": systemPrompt}]

# Step 1: Get original input
userInput = input("Describe your workout today: ")
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

# Get today's date
dateStr = datetime.now().strftime("%Y-%m-%d")

# Log to CSV
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
