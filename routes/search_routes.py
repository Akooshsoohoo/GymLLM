from flask import Blueprint, render_template_string, redirect, url_for, request
from flask_dance.contrib.google import google
from models.models import db, Workout
from app import SEARCH_TEMPLATE

search_bp = Blueprint('search_bp', __name__)

@search_bp.route("/search", methods=["GET", "POST"])
def search():
    user_email = None
    if google.authorized:
        try:
            resp = google.get("/oauth2/v2/userinfo")
            if resp.ok:
                user_email = resp.json().get("email")
        except Exception:
            pass
    if not user_email:
        return redirect(url_for("auth.login"))

    workouts = Workout.query.filter_by(user_email=user_email).all()
    rows = [
        [w.date, w.exercise, w.weight, w.sets, w.reps, w.notes, w.tags]
        for w in workouts
    ]

    if request.method == "POST":
        num_rows = int(request.form.get("num_rows", 0))
        num_cols = int(request.form.get("num_cols", 7))
        new_data = []
        ids_to_delete = []
        for i in range(num_rows):
            row = []
            for j in range(num_cols):
                row.append(request.form.get(f"cell-{i}-{j}", ""))
            if request.form.get(f"delete-{i}"):
                ids_to_delete.append(i)
            else:
                new_data.append(row)
        for idx in sorted(ids_to_delete, reverse=True):
            w = workouts[idx]
            db.session.delete(w)
        db.session.commit()
        for idx, row in enumerate(new_data):
            w = workouts[idx]
            w.date, w.exercise, w.weight, w.sets, w.reps, w.notes, w.tags = row
        db.session.commit()
        return redirect(url_for("search_bp.search"))

    return render_template_string(SEARCH_TEMPLATE, rows=rows)
