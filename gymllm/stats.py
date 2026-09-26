"""Aggregations behind the Progress pages: time ranges, day/week/month grouping,
training volume and the overview dashboard. Pure functions over row dicts
(Workout.as_dict()) so they are easy to test without a database."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta

RANGES: dict[str, int | None] = {"7d": 7, "30d": 30, "90d": 90, "1y": 365, "all": None}
RANGE_LABELS = {
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
    "1y": "1 year",
    "all": "All time",
}
GROUPINGS = ("day", "week", "month")
DEFAULT_GROUPING = {"7d": "day", "30d": "day", "90d": "week", "1y": "month", "all": "month"}
TOP_N = 8
LIFTS_N = 6  # exercise progress charts on the Overview
TAGS_N = 10  # muscle tags shown before the rest fold into "other"
# Tags that describe the movement rather than a muscle; left out of the muscle-group chart.
MOVEMENT_TAGS = {"compound", "isolation", "isolated", "push", "pull", "upper", "lower", "rowing"}

_WEIGHT_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)")
_INT_RE = re.compile(r"\d+")
_QUANTITY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)")
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]*)")
_CLOCK_RE = re.compile(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*$")
_DISTANCE_UNITS = {
    "mi": "mi", "mile": "mi", "miles": "mi",
    "km": "km", "kms": "km", "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km", "k": "km",
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "yd": "yd", "yard": "yd", "yards": "yd",
    "ft": "ft", "foot": "ft", "feet": "ft",
    "lap": "laps", "laps": "laps",
}  # fmt: skip
_HOUR_UNITS = {"h", "hr", "hrs", "hour", "hours"}
_SECOND_UNITS = {"s", "sec", "secs", "second", "seconds"}
_MINUTE_UNITS = {"", "m", "min", "mins", "minute", "minutes"}
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


# --- Parsing the free-text columns -------------------------------------------


def weight_number(weight: str | None) -> float | None:
    """'185 lbs' -> 185.0; 'bodyweight' -> None."""
    m = _WEIGHT_NUM_RE.match(weight or "")
    return float(m.group(1)) if m else None


def reps_list(reps: str | None) -> list[int]:
    """'10, 8, 6' -> [10, 8, 6]; '[12, 12]' -> [12, 12]; '' -> []."""
    return [int(n) for n in _INT_RE.findall(reps or "")]


def total_reps(sets: str | None, reps: str | None) -> int | None:
    """Reps across all sets. A single reps number is multiplied by the set count."""
    per_set = reps_list(reps)
    if not per_set:
        return None
    if len(per_set) == 1 and (sets or "").strip().isdigit():
        return int(sets) * per_set[0]
    return sum(per_set)


def set_count(sets: str | None, reps: str | None) -> int:
    """'5', '5, 5, 5, 5, 5' -> 5; '', '10, 8, 6' -> 3; '', '' -> 0."""
    if (sets or "").strip().isdigit():
        return int(sets)
    return len(reps_list(reps))


def entry_volume(row: dict) -> float | None:
    """weight x total reps, or None when either is not a number (e.g. bodyweight)."""
    weight = weight_number(row.get("weight"))
    reps = total_reps(row.get("sets"), row.get("reps"))
    if weight is None or reps is None:
        return None
    return weight * reps


def quantity(text: str | None) -> tuple[float, str] | None:
    """'3 miles' -> (3.0, 'mi'); '130 lbs' -> (130.0, 'lbs'); 'bodyweight' -> None."""
    m = _QUANTITY_RE.match(text or "")
    if not m:
        return None
    unit = m.group(2).lower()
    return float(m.group(1)), _DISTANCE_UNITS.get(unit, unit)


def duration_minutes(text: str | None) -> float | None:
    """'45 min' -> 45; '1 h 20 min' -> 80; '1:20:00' -> 80; '45:30' -> 45.5; '' -> None."""
    text = (text or "").strip().lower()
    if not text:
        return None
    m = _CLOCK_RE.match(text)
    if m:
        h, mm, ss = m.group(1), m.group(2), m.group(3)
        if ss is None:  # mm:ss
            return int(h) + int(mm) / 60
        return int(h) * 60 + int(mm) + int(ss) / 60
    total = 0.0
    found = False
    for num, unit in _DURATION_PART_RE.findall(text):
        found = True
        n = float(num)
        if unit in _HOUR_UNITS:
            total += n * 60
        elif unit in _SECOND_UNITS:
            total += n / 60
        elif unit in _MINUTE_UNITS:
            total += n
    return total if found else None


def format_minutes(minutes: float | None) -> str:
    if not minutes:
        return ""
    whole = int(round(minutes))
    h, m = divmod(whole, 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def format_number(n: float) -> str:
    return f"{n:,.0f}" if n == int(n) else f"{n:,.1f}"


def distance_totals(cardio: list[dict]) -> dict[str, float]:
    """Distance summed per unit, the most-used unit first: {'mi': 12.5, 'laps': 40}."""
    totals: dict[str, float] = defaultdict(float)
    uses: Counter[str] = Counter()
    for c in cardio:
        q = quantity(c.get("distance"))
        if q:
            totals[q[1]] += q[0]
            uses[q[1]] += 1
    return dict(sorted(totals.items(), key=lambda kv: (-uses[kv[0]], -kv[1])))


def format_distance(totals: dict[str, float]) -> str:
    return " + ".join(f"{format_number(v)} {u}".strip() for u, v in totals.items())


def cardio_stats(cardio: list[dict]) -> dict:
    minutes = sum(m for m in (duration_minutes(c.get("duration")) for c in cardio) if m)
    totals = distance_totals(cardio)
    first = next(iter(totals.items()), None)
    return {
        "count": len(cardio),
        "distance": totals,
        "distance_text": format_distance(totals),
        "lead": f"{format_number(first[1])} {first[0]}".strip() if first else "",
        "rest": format_distance(dict(list(totals.items())[1:])),
        "minutes": minutes,
        "minutes_text": format_minutes(minutes),
    }


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# --- Ranges and periods --------------------------------------------------------


def clean_range(value: str | None, default: str = "all") -> str:
    return value if value in RANGES else default


def clean_grouping(value: str | None, range_key: str) -> str:
    return value if value in GROUPINGS else DEFAULT_GROUPING[range_key]


def range_start(today: date, range_key: str) -> date | None:
    days = RANGES[range_key]
    return None if days is None else today - timedelta(days=days - 1)


def filter_range(rows: list[dict], today: date, range_key: str) -> list[dict]:
    start = range_start(today, range_key)
    if start is None:
        return list(rows)
    lo = start.isoformat()
    return [r for r in rows if r["date"] >= lo]


def period_key(d: date, by: str) -> str:
    if by == "week":
        return (d - timedelta(days=d.weekday())).isoformat()  # the Monday
    if by == "month":
        return f"{d.year:04d}-{d.month:02d}"
    return d.isoformat()


def period_label(key: str, by: str) -> str:
    if by == "month":
        y, m = key.split("-")
        return f"{_MONTHS[int(m) - 1]} {y}"
    d = date.fromisoformat(key)
    if by == "week":
        end = d + timedelta(days=6)
        if d.month == end.month:
            return f"{d.day}–{end.day} {d:%b} {d.year}"
        return f"{d.day} {d:%b} – {end.day} {end:%b} {end.year}"
    return f"{d:%a} {d.day} {d:%b} {d.year}"


def period_short(key: str, by: str) -> str:
    """Axis label: '12 Jan', 'Jan 2026'."""
    if by == "month":
        y, m = key.split("-")
        return f"{_MONTHS[int(m) - 1][:3]} {y}"
    d = date.fromisoformat(key)
    return f"{d.day} {d:%b}"


def period_next(key: str, by: str) -> str:
    if by == "month":
        y, m = (int(p) for p in key.split("-"))
        return f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
    step = 7 if by == "week" else 1
    return (date.fromisoformat(key) + timedelta(days=step)).isoformat()


def period_keys(start: date, end: date, by: str) -> list[str]:
    """Every period key from the one containing `start` to the one containing `end`."""
    keys: list[str] = []
    key, last = period_key(start, by), period_key(end, by)
    while key <= last:
        keys.append(key)
        key = period_next(key, by)
    return keys


# --- Grouping ------------------------------------------------------------------


def _summarise(rows: list[dict]) -> dict:
    volume = sum(v for v in (entry_volume(r) for r in rows) if v is not None)
    return {
        "entries": len(rows),
        "sessions": len({r["date"] for r in rows}),
        "exercises": len({r["exercise"] for r in rows}),
        "volume": volume,
    }


def _bucket(items: list[dict], by: str, unparsable: set[str]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in items:
        d = parse_date(r["date"])
        if d is None:
            unparsable.add(r["date"])
        buckets[period_key(d, by) if d else r["date"]].append(r)
    return buckets


def group_rows(
    rows: list[dict], by: str, cardio: list[dict] = (), weights: list[dict] = ()
) -> list[dict]:
    """Strength rows, cardio and weigh-ins (any order) -> groups newest first, each
    holding its rows/cardio/weights newest first plus a summary."""
    unparsable: set[str] = set()  # rows whose date is not ISO are grouped under it verbatim
    strength = _bucket(rows, by, unparsable)
    activities = _bucket(list(cardio), by, unparsable)
    readings = _bucket(list(weights), by, unparsable)
    newest = lambda r: (r["date"], r["id"])  # noqa: E731
    groups = []
    for key in sorted(set(strength) | set(activities) | set(readings), reverse=True):
        members = sorted(strength.get(key, []), key=newest, reverse=True)
        group_cardio = sorted(activities.get(key, []), key=newest, reverse=True)
        group_weights = sorted(readings.get(key, []), key=newest, reverse=True)
        summary = _summarise(members)
        summary["sessions"] = len({r["date"] for r in members} | {c["date"] for c in group_cardio})
        summary.update(
            key=key,
            label=key if key in unparsable else period_label(key, by),
            rows=members,
            cardio=group_cardio,
            cardio_text=format_distance(distance_totals(group_cardio)),
            weights=group_weights,
        )
        groups.append(summary)
    return groups


def day_summary(rows: list[dict], cardio: list[dict]) -> dict:
    """Totals for one day: exercises, sets, reps, volume and the cardio stats."""
    summary = _summarise(rows)
    summary["sets"] = sum(set_count(r.get("sets"), r.get("reps")) for r in rows)
    summary["reps"] = sum(total_reps(r.get("sets"), r.get("reps")) or 0 for r in rows)
    summary["cardio"] = cardio_stats(list(cardio))
    return summary


# --- Overview dashboard --------------------------------------------------------


def week_streak(dates: set[str], today: date) -> int:
    """Consecutive weeks with at least one session, counting back from this week
    (or from last week if this week has nothing yet)."""
    weeks = {period_key(d, "week") for d in (parse_date(v) for v in dates) if d}
    this_week = date.fromisoformat(period_key(today, "week"))
    cursor = this_week
    if this_week.isoformat() not in weeks:
        cursor = this_week - timedelta(days=7)
    streak = 0
    while cursor.isoformat() in weeks:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def personal_records(all_rows: list[dict], start: date | None) -> list[dict]:
    """Entries on/after `start` whose weight beat every earlier entry of that exercise."""
    best: dict[str, float] = {}
    prs = []
    lo = start.isoformat() if start else ""
    for r in sorted(all_rows, key=lambda r: (r["date"], r["id"])):
        n = weight_number(r["weight"])
        if n is None:
            continue
        prev = best.get(r["exercise"])
        if prev is None or n > prev:
            if r["date"] >= lo and prev is not None:
                prs.append({**r, "previous": prev, "value": n})
            best[r["exercise"]] = n
    prs.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    return prs


def week_strip(
    today: date,
    rows: list[dict],
    cardio: list[dict] = (),
    weights: list[dict] = (),
    week: date | None = None,
) -> list[dict]:
    """Monday to Sunday of the week holding `week` (default: today): whether anything
    was logged each day, plus that day's exercise count, sets, cardio and weigh-in
    for the labels under it."""
    monday = date.fromisoformat(period_key(week or today, "week"))
    lo, hi = monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    per_day: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for kind, items in (("rows", rows), ("cardio", cardio), ("weights", weights)):
        for x in items:
            if lo <= x["date"] <= hi:
                per_day[x["date"]][kind].append(x)
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        logged = per_day.get(d.isoformat(), {})
        lifts, activities = logged.get("rows", []), logged.get("cardio", [])
        readings = sorted(logged.get("weights", []), key=lambda w: w["id"])
        st = cardio_stats(activities)
        days.append(
            {
                "date": d.isoformat(),
                "letter": "MTWTFSS"[i],
                "day": d.day,
                "logged": bool(logged),
                "today": d == today,
                "future": d > today,
                "exercises": len({r["exercise"] for r in lifts}),
                "sets": sum(set_count(r.get("sets"), r.get("reps")) for r in lifts),
                "cardio_text": st["lead"] or st["minutes_text"] or ("cardio" if activities else ""),
                "weight": readings[-1]["weight"] if readings else "",
            }
        )
    return days


def lift_progress(rows: list[dict], n: int = LIFTS_N) -> list[dict]:
    """The most-trained lifts with at least two weighed sessions: their top weight
    per session and the change from the first session to the latest."""
    per_ex: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per_ex[r["exercise"]].append(r)
    lifts = []
    for name, members in per_ex.items():
        series = [p for p in exercise_series(members) if p["weight"] is not None]
        if len(series) < 2:
            continue
        units = {
            r["date"]: q[1]
            for r in sorted(members, key=lambda r: (r["date"], r["id"]))
            for q in [quantity(r["weight"])]
            if q
        }
        first, latest = series[0], series[-1]
        unit = units.get(latest["date"], "")
        change = pct = None
        if units.get(first["date"], "") == unit:
            change = latest["weight"] - first["weight"]
            pct = round(100 * change / first["weight"]) if first["weight"] else None
        lifts.append(
            {
                "exercise": name,
                "series": series,
                "first": first["weight"],
                "latest": latest["weight"],
                "change": change,
                "pct": pct,
                "unit": unit,
            }
        )
    lifts.sort(key=lambda x: (len(x["series"]), x["series"][-1]["date"]), reverse=True)
    return lifts[:n]


def totals(rows: list[dict], cardio: list[dict]) -> dict:
    """Entries, exercises, sets, volume... plus sessions (days with anything),
    cardio activities and cardio minutes."""
    out = _summarise(rows)
    out["sessions"] = len({r["date"] for r in rows} | {c["date"] for c in cardio})
    out["cardio"] = len(cardio)
    out["minutes"] = sum(m for m in (duration_minutes(c.get("duration")) for c in cardio) if m)
    return out


def bodyweight_summary(
    weights: list[dict], start: date | None, today: date | None = None, by: str = "day"
) -> dict | None:
    """Latest reading in the range, its change since the first one in the range, and
    a per-period series (average of the readings in each day/week/month) spanning
    the whole range so the chart shares the axis of the other Overview charts."""
    lo = start.isoformat() if start else ""
    readings = sorted((w for w in weights if w["date"] >= lo), key=lambda w: (w["date"], w["id"]))
    if not readings:
        return None
    series = []
    for w in readings:
        q = quantity(w["weight"])
        if q:
            series.append({"date": w["date"], "weight": q[0], "unit": q[1], "text": w["weight"]})
    latest = readings[-1]
    change = None
    if len(series) >= 2 and series[0]["unit"] == series[-1]["unit"]:
        change = series[-1]["weight"] - series[0]["weight"]
    # Chart in the unit used most often (ties go to the latest reading's unit);
    # readings in another unit are left out of the chart.
    uses = Counter(p["unit"] for p in series)
    unit = max(uses, key=lambda u: (uses[u], u == series[-1]["unit"])) if uses else ""
    periods = bodyweight_periods([p for p in series if p["unit"] == unit], start, today, by)
    return {
        "latest": latest["weight"],
        "latest_date": latest["date"],
        "change": change,
        "unit": series[-1]["unit"] if series else "",
        "since": series[0]["date"] if len(series) >= 2 else None,
        "series": series,
        "chart_unit": unit,
        "periods": periods,
        "charted": sum(1 for p in periods if p["weight"] is not None),
    }


def bodyweight_periods(
    points: list[dict], start: date | None, today: date | None, by: str
) -> list[dict]:
    """One point per period from `start` (or the first reading) to `today`: the
    average weight of that period's readings, or None when there were none."""
    dated = [(d, p["weight"]) for p in points for d in [parse_date(p["date"])] if d]
    if not dated:
        return []
    first = min(d for d, _ in dated)
    end = max([today or first] + [d for d, _ in dated])
    per_key: dict[str, list[float]] = defaultdict(list)
    for d, w in dated:
        per_key[period_key(d, by)].append(w)
    out = []
    for key in period_keys(start or first, end, by):
        values = per_key.get(key, [])
        many = len(values) > 1
        out.append(
            {
                "key": key,
                "label": period_short(key, by),
                "weight": round(sum(values) / len(values), 1) if values else None,
                "readings": len(values)
                if many
                else None,  # tooltip row only when it adds something
                "low": min(values) if many else None,
                "high": max(values) if many else None,
            }
        )
    return out


def cardio_summary(cardio: list[dict]) -> list[dict]:
    """Per activity: how often, total distance and time, and the last date."""
    per: dict[str, list[dict]] = defaultdict(list)
    for c in cardio:
        per[c["activity"]].append(c)
    out = []
    for name, items in per.items():
        st = cardio_stats(items)
        out.append(
            {
                "activity": name,
                "count": len(items),
                "distance_text": st["distance_text"],
                "minutes_text": st["minutes_text"],
                "last": max(c["date"] for c in items),
            }
        )
    out.sort(key=lambda a: (a["last"], a["activity"]), reverse=True)
    return out


def tag_counts(rows: list[dict], n: int = TAGS_N) -> list[dict]:
    """Entries per muscle tag, the top `n` and the rest folded into "other"."""
    counts: Counter[str] = Counter()
    for r in rows:
        for t in (r.get("tags") or "").split(";"):
            t = t.strip()
            if t and t not in MOVEMENT_TAGS:
                counts[t] += 1
    tags = [{"tag": t, "count": c} for t, c in counts.most_common(n)]
    rest = sum(counts.values()) - sum(t["count"] for t in tags)
    if rest:
        tags.append({"tag": "other", "count": rest})
    return tags


def top_exercises(rows: list[dict], n: int = TOP_N) -> list[dict]:
    """The most-logged exercises with their session count, best weight and last date."""
    per_ex: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per_ex[r["exercise"]].append(r)
    top = []
    for name, members in sorted(per_ex.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:n]:
        weighed = [(weight_number(r["weight"]), r["weight"]) for r in members]
        weighed = [w for w in weighed if w[0] is not None]
        top.append(
            {
                "exercise": name,
                "entries": len(members),
                "sessions": len({r["date"] for r in members}),
                "best": max(weighed)[1] if weighed else "",
                "last": max(r["date"] for r in members),
            }
        )
    return top


def sessions_per_period(dates: set[str], today: date, by: str = "week", n: int = 12) -> list[dict]:
    """Days with anything logged in each of the last `n` days/weeks/months up to today,
    oldest first. The last one is the current period."""
    key = period_key(today, by)
    keys = [key]
    for _ in range(n - 1):
        if by == "month":
            y, m = (int(p) for p in key.split("-"))
            key = f"{y - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"
        else:
            key = (date.fromisoformat(key) - timedelta(days=7 if by == "week" else 1)).isoformat()
        keys.append(key)
    keys.reverse()
    counts = Counter(period_key(d, by) for d in map(parse_date, dates) if d and d <= today)
    return [
        {
            "label": period_short(k, by),
            "title": period_label(k, by),
            "sessions": counts.get(k, 0),
            "current": k == keys[-1],
        }
        for k in keys
    ]


def overview(
    all_rows: list[dict],
    today: date,
    range_key: str,
    by: str,
    cardio: list[dict] = (),
    weights: list[dict] = (),
    week: date | None = None,
) -> dict:
    rows = filter_range(all_rows, today, range_key)
    activities = filter_range(list(cardio), today, range_key)
    start = range_start(today, range_key)
    return {
        "range": range_key,
        "by": by,
        "start": start,
        "totals": totals(rows, activities),
        "cardio": cardio_stats(activities),
        "per_period": sessions_per_period(
            {r["date"] for r in all_rows} | {c["date"] for c in cardio}, today, by
        ),
        "bodyweight": bodyweight_summary(list(weights), start, today, by),
        "streak": week_streak({r["date"] for r in all_rows}, today),
        "week": week_strip(today, all_rows, list(cardio), list(weights), week),
        "lifts": lift_progress(rows),
        "tags": tag_counts(rows),
        "top_exercises": top_exercises(rows),
        "prs": personal_records(all_rows, start)[:TOP_N],
    }


# --- Per-exercise series -------------------------------------------------------


def exercise_series(rows: list[dict]) -> list[dict]:
    """One point per session date: top weight, total volume, total reps."""
    per_date: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["date"], r["id"])):
        p = per_date.setdefault(
            r["date"], {"date": r["date"], "weight": None, "volume": 0.0, "reps": 0}
        )
        w = weight_number(r["weight"])
        if w is not None and (p["weight"] is None or w > p["weight"]):
            p["weight"] = w
        v = entry_volume(r)
        if v is not None:
            p["volume"] += v
        p["reps"] += total_reps(r["sets"], r["reps"]) or 0
    return [per_date[d] for d in sorted(per_date)]
