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
HEATMAP_MAX_WEEKS = 53
TOP_N = 8
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


def _delta(current: float, previous: float | None) -> float | None:
    return None if previous is None else current - previous


def _totals(rows: list[dict], cardio: list[dict]) -> dict:
    totals = _summarise(rows)
    totals["sessions"] = len({r["date"] for r in rows} | {c["date"] for c in cardio})
    totals["cardio"] = len(cardio)
    totals["minutes"] = sum(m for m in (duration_minutes(c.get("duration")) for c in cardio) if m)
    return totals


def bodyweight_summary(weights: list[dict], start: date | None) -> dict | None:
    """Latest reading in the range and its change since the first one in the range."""
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
    return {
        "latest": latest["weight"],
        "latest_date": latest["date"],
        "change": change,
        "unit": series[-1]["unit"] if series else "",
        "since": series[0]["date"] if len(series) >= 2 else None,
        "series": series,
    }


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


def overview(
    all_rows: list[dict],
    today: date,
    range_key: str,
    by: str,
    cardio: list[dict] = (),
    weights: list[dict] = (),
) -> dict:
    rows = filter_range(all_rows, today, range_key)
    activities = filter_range(list(cardio), today, range_key)
    start = range_start(today, range_key)
    totals = _totals(rows, activities)

    # Same-length window immediately before this one, for the deltas.
    previous = None
    if start is not None:
        days = RANGES[range_key] or 0
        prev_lo, prev_hi = (start - timedelta(days=days)).isoformat(), start.isoformat()
        previous = _totals(
            [r for r in all_rows if prev_lo <= r["date"] < prev_hi],
            [c for c in cardio if prev_lo <= c["date"] < prev_hi],
        )

    # Activity per period, zero-filled across the whole range.
    dated = [parse_date(x["date"]) for x in rows + activities]
    first = min((d for d in dated if d), default=None)
    chart_start = start or first
    by_period: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = parse_date(r["date"])
        if d:
            by_period[period_key(d, by)].append(r)
    cardio_by_period: dict[str, list[dict]] = defaultdict(list)
    for c in activities:
        d = parse_date(c["date"])
        if d:
            cardio_by_period[period_key(d, by)].append(c)
    unit = next(iter(distance_totals(activities)), "")  # the unit with the most distance
    activity = []
    cardio_series = []
    if chart_start is not None:
        for key in period_keys(chart_start, today, by):
            s = _summarise(by_period.get(key, []))
            activity.append({"key": key, "label": period_short(key, by), **s})
            st = cardio_stats(cardio_by_period.get(key, []))
            cardio_series.append(
                {
                    "key": key,
                    "label": period_short(key, by),
                    "distance": st["distance"].get(unit, 0.0),
                    "activities": st["count"],
                    "minutes": st["minutes"],
                }
            )

    # Calendar heatmap: entries per day, Monday-aligned weeks ending today.
    heat_start = chart_start or today
    heat_start = max(heat_start, today - timedelta(weeks=HEATMAP_MAX_WEEKS - 1))
    heat_start -= timedelta(days=heat_start.weekday())
    per_day = Counter(x["date"] for x in rows + activities)
    heatmap = [
        {"date": (heat_start + timedelta(days=i)).isoformat(), "count": 0}
        for i in range((today - heat_start).days + 1)
    ]
    for cell in heatmap:
        cell["count"] = per_day.get(cell["date"], 0)

    # Muscle groups: entries per tag, top N and the rest folded into "other".
    tag_counts: Counter[str] = Counter()
    for r in rows:
        for t in (r.get("tags") or "").split(";"):
            t = t.strip()
            if t and t not in MOVEMENT_TAGS:
                tag_counts[t] += 1
    tags = [{"tag": t, "count": c} for t, c in tag_counts.most_common(TAGS_N)]
    rest = sum(tag_counts.values()) - sum(t["count"] for t in tags)
    if rest:
        tags.append({"tag": "other", "count": rest})

    # Most-trained exercises in the range, with their best weight in the range.
    per_ex: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per_ex[r["exercise"]].append(r)
    top = []
    for name, members in sorted(per_ex.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_N]:
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

    return {
        "range": range_key,
        "by": by,
        "start": start,
        "totals": totals,
        "deltas": {
            k: _delta(totals[k], previous[k] if previous else None)
            for k in ("sessions", "entries", "volume", "cardio")
        },
        "cardio": cardio_stats(activities),
        "cardio_series": cardio_series,
        "distance_unit": unit,
        "bodyweight": bodyweight_summary(list(weights), start),
        "weights_total": len(weights),
        "streak": week_streak({r["date"] for r in all_rows}, today),
        "activity": activity,
        "heatmap": heatmap,
        "tags": tags,
        "top_exercises": top,
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
