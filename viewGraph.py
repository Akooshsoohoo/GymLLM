import os
from dotenv import load_dotenv
load_dotenv()
import pandas as pd
import matplotlib.pyplot as plt
from openai import OpenAI


# === Load canonical exercises ===
with open("exerciseList.csv", newline="") as f:
    validExercises = [line.strip().lower() for line in f if line.strip()]

# === Get vague user input ===
userExerciseInput = input("What exercise do you want to graph (can be vague): ").strip()

# === Use GPT to map input to canonical name ===
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
systemPrompt = (
    "You are a workout assistant. Match vague or informal exercise descriptions "
    "to a list of known exercises. Only return the closest match from this list:\n"
    + ", ".join(validExercises)
)

response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": systemPrompt},
        {"role": "user", "content": f"My input: {userExerciseInput}"}
    ]
)

mappedExercise = response.choices[0].message.content.strip().lower()
print(f"\n→ Interpreted as: {mappedExercise}\n")

# === Load and filter workout data ===
df = pd.read_csv("workoutLog.csv", header=None, names=["date", "exercise", "weight", "sets", "reps", "notes"])
df = df[df["exercise"].str.lower() == mappedExercise]

# Parse date
df["date"] = pd.to_datetime(df["date"])

# === Ask graph mode ===
print("Choose a graph mode:")
print("1. Total volume (sum of all sets × weight)")
print("2. Top set weight")
print("3. Top set estimated 1RM (Epley formula)")
mode = input("Enter 1, 2, or 3: ").strip()

# === Metric calculation ===
def tryParse(row):
    try:
        reps = eval(row["reps"])  # stored as list
        weight = float(row["weight"].replace("lbs", "").strip())
        return reps, weight
    except:
        return None, None

xDates, yValues = [], []

for _, row in df.iterrows():
    reps, weight = tryParse(row)
    if reps is None or weight is None:
        continue

    date = row["date"]

    if mode == "1":
        y = weight * sum(reps)
    elif mode == "2":
        y = weight
    elif mode == "3":
        y = weight * (1 + max(reps) / 30)
    else:
        print("Invalid mode.")
        exit()

    xDates.append(date)
    yValues.append(y)

# === Plotting ===
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 6))
plt.plot(xDates, yValues, marker="o")
modeNames = {"1": "Total Volume", "2": "Top Set Weight", "3": "Estimated 1RM"}
plt.title(f"{modeNames.get(mode, 'Progress')} for: {mappedExercise}")
plt.xlabel("Date")
plt.ylabel(modeNames.get(mode, "Metric"))
plt.grid(True)
plt.tight_layout()
plt.show()
