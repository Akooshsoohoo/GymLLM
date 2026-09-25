"""Side-by-side stats for two people (you and a friend). Pure functions over the
row dicts social.visible_data() returns, so they test without a database."""

from __future__ import annotations

from datetime import date, timedelta

from . import stats

FAVOURITES_N = 5
TAGS_N = 8
WEEKS_N = 12
_UNIT_ALIASES = {
    "lb": "lbs", "lbs": "lbs", "pound": "lbs", "pounds": "lbs",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg",
}  # fmt: skip


def weight_in_unit(weight: str | None, default_unit: str) -> tuple[float, str] | None:
    """'185 lbs' -> (185.0, 'lbs'); '80' -> (80.0, default_unit); 'bodyweight' -> None.
    Units other than lbs/kg are kept as written so they never compare equal to them."""
    q = stats.quantity(weight)
    if q is None:
        return None
    value, unit = q
    return value, (_UNIT_ALIASES.get(unit, unit) if unit else default_unit)


def best_lifts(rows: list[dict], default_unit: str) -> dict[str, dict]:
    """Per exercise (keyed by lowercase name): the heaviest weight in the unit the
    person uses most for it, plus session count and last date."""
    per_ex: dict[str, list[dict]] = {}
    for r in rows:
        per_ex.setdefault(r["exercise"].strip().lower(), []).append(r)
    out = {}
    for key, members in per_ex.items():
        weighed = [
            (w, r) for r in members for w in [weight_in_unit(r["weight"], default_unit)] if w
        ]
        entry = {
            "exercise": members[0]["exercise"],
            "sessions": len({r["date"] for r in members}),
            "last": max(r["date"] for r in members),
            "value": None,
            "unit": "",
            "text": "",
        }
        if weighed:
            units = [w[1] for w, _ in weighed]
            unit = max(set(units), key=lambda u: (units.count(u), u == default_unit))
            (value, _), row = max(
                ((w, r) for w, r in weighed if w[1] == unit), key=lambda x: x[0][0]
            )
            entry.update(value=value, unit=unit, text=row["weight"])
        out[key] = entry
    return out


def _lead(mine: float | None, theirs: float | None) -> str | None:
    if mine is None or theirs is None or mine == theirs:
        return None
    return "mine" if mine > theirs else "theirs"


def _person_totals(rows: list[dict], cardio: list[dict], all_dates: set[str], today: date) -> dict:
    t = stats.totals(rows, cardio)
    t["sets"] = sum(stats.set_count(r.get("sets"), r.get("reps")) for r in rows)
    t["streak"] = stats.week_streak(all_dates, today)
    return t


def shared_lifts(mine: dict[str, dict], theirs: dict[str, dict]) -> list[dict]:
    """Exercises both people trained, most trained together first. A leader and a
    difference only when both weights are in the same unit."""
    out = []
    for key in mine.keys() & theirs.keys():
        a, b = mine[key], theirs[key]
        comparable = a["value"] is not None and b["value"] is not None and a["unit"] == b["unit"]
        out.append(
            {
                "exercise": a["exercise"],
                "mine": a,
                "theirs": b,
                "lead": _lead(a["value"], b["value"]) if comparable else None,
                "diff": abs(a["value"] - b["value"]) if comparable else None,
                "unit": a["unit"] if comparable else "",
            }
        )
    out.sort(key=lambda s: (-(s["mine"]["sessions"] + s["theirs"]["sessions"]), s["exercise"]))
    return out


def muscle_split(mine: list[dict], theirs: list[dict], n: int = TAGS_N) -> list[dict]:
    """Each tag's share of each person's tagged entries (so a busier person doesn't
    dwarf the other), the tags most trained between the two first."""
    a = {t["tag"]: t["count"] for t in stats.tag_counts(mine, n=100) if t["tag"] != "other"}
    b = {t["tag"]: t["count"] for t in stats.tag_counts(theirs, n=100) if t["tag"] != "other"}
    total_a, total_b = sum(a.values()) or 1, sum(b.values()) or 1
    tags = sorted(
        a.keys() | b.keys(), key=lambda t: (-(a.get(t, 0) / total_a + b.get(t, 0) / total_b), t)
    )
    return [
        {
            "tag": t,
            "mine": round(100 * a.get(t, 0) / total_a),
            "theirs": round(100 * b.get(t, 0) / total_b),
        }
        for t in tags[:n]
    ]


def weekly_sessions(
    mine_dates: set[str], theirs_dates: set[str], today: date, weeks: int = WEEKS_N
) -> list[dict]:
    """Sessions (days with anything logged) per week for the last `weeks` weeks."""
    this_monday = date.fromisoformat(stats.period_key(today, "week"))
    start = this_monday - timedelta(weeks=weeks - 1)

    def per_week(dates: set[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in filter(None, map(stats.parse_date, dates)):
            if start <= d <= today:
                key = stats.period_key(d, "week")
                counts[key] = counts.get(key, 0) + 1
        return counts

    a, b = per_week(mine_dates), per_week(theirs_dates)
    return [
        {"label": stats.period_short(key, "week"), "mine": a.get(key, 0), "theirs": b.get(key, 0)}
        for key in stats.period_keys(start, today, "week")
    ]


def compare(
    mine: tuple[list[dict], list[dict]],
    theirs: tuple[list[dict], list[dict]],
    today: date,
    range_key: str,
    my_unit: str = "lbs",
    their_unit: str = "lbs",
) -> dict:
    """Everything the Compare page shows. `mine`/`theirs` are (rows, cardio)."""
    (my_rows_all, my_cardio_all), (their_rows_all, their_cardio_all) = mine, theirs
    my_dates = {x["date"] for x in my_rows_all + my_cardio_all}
    their_dates = {x["date"] for x in their_rows_all + their_cardio_all}
    my_rows = stats.filter_range(my_rows_all, today, range_key)
    their_rows = stats.filter_range(their_rows_all, today, range_key)
    a = _person_totals(
        my_rows, stats.filter_range(my_cardio_all, today, range_key), my_dates, today
    )
    b = _person_totals(
        their_rows, stats.filter_range(their_cardio_all, today, range_key), their_dates, today
    )
    same_unit = my_unit == their_unit
    totals = [
        {"label": "Sessions", "mine": a["sessions"], "theirs": b["sessions"]},
        {"label": "Sets", "mine": a["sets"], "theirs": b["sets"]},
        {"label": "Exercises", "mine": a["exercises"], "theirs": b["exercises"]},
        {"label": "Cardio minutes", "mine": a["minutes"], "theirs": b["minutes"]},
        {"label": "Week streak", "mine": a["streak"], "theirs": b["streak"]},
        {
            "label": f"Volume ({my_unit})" if same_unit else "Volume",
            "mine": a["volume"],
            "theirs": b["volume"],
            "units": None if same_unit else (my_unit, their_unit),
        },
    ]
    for t in totals:
        t["lead"] = None if t.get("units") else _lead(t["mine"], t["theirs"])

    my_favs = stats.top_exercises(my_rows, FAVOURITES_N)
    their_favs = stats.top_exercises(their_rows, FAVOURITES_N)
    my_names = {f["exercise"].lower() for f in my_favs}
    their_names = {f["exercise"].lower() for f in their_favs}
    for f in my_favs:
        f["shared"] = f["exercise"].lower() in their_names
    for f in their_favs:
        f["shared"] = f["exercise"].lower() in my_names

    return {
        "totals": totals,
        "shared": shared_lifts(best_lifts(my_rows, my_unit), best_lifts(their_rows, their_unit)),
        "favourites": {"mine": my_favs, "theirs": their_favs},
        "muscles": muscle_split(my_rows, their_rows),
        "weekly": weekly_sessions(my_dates, their_dates, today),
        "empty": not (my_rows or their_rows or a["cardio"] or b["cardio"]),
    }
