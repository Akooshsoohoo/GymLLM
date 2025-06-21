import pandas as pd

def load_tagged_exercise_list(path="taggedExerciseList.csv"):
    df = pd.read_csv(path)
    df["exercise"] = df["exercise"].str.lower().str.strip()
    return df

tag_df = load_tagged_exercise_list()
exerciseListText = ", ".join(tag_df["exercise"].tolist())
