import tkinter as tk
from tkinter import ttk
import pandas as pd

# Load workout log
LOG_PATH = "workoutLog.csv"

def load_data():
    try:
        return pd.read_csv(LOG_PATH)
    except FileNotFoundError:
        return pd.DataFrame(columns=["date", "exercise", "weight", "sets", "reps", "notes", "tags"])

def filter_data(df, query):
    query = query.lower()
    return df[df.apply(lambda row: query in row.to_string().lower(), axis=1)]

def update_tree(tree, data):
    tree.delete(*tree.get_children())
    for _, row in data.iterrows():
        tree.insert("", "end", values=list(row))

def main():
    df = load_data()

    root = tk.Tk()
    root.title("Workout Log Search")

    tk.Label(root, text="Search (name or tag):").pack()
    search_var = tk.StringVar()
    search_box = tk.Entry(root, textvariable=search_var)
    search_box.pack(fill="x")

    cols = ["date", "exercise", "weight", "sets", "reps", "notes", "tags"]
    tree = ttk.Treeview(root, columns=cols, show="headings")
    for col in cols:
        tree.heading(col, text=col)
        tree.column(col, width=100)
    tree.pack(fill="both", expand=True)

    def on_search(*_):
        query = search_var.get()
        filtered = filter_data(df, query)
        update_tree(tree, filtered)

    search_box.bind("<KeyRelease>", on_search)
    update_tree(tree, df)
    root.mainloop()

if __name__ == "__main__":
    main()
