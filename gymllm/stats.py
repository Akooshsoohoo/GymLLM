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


def group_rows(rows: list[dict], by: str) -> list[dict]:
    """Rows (any order) -> groups newest first, each with its rows newest first."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    unparsable: set[str] = set()  # rows whose date is not ISO are grouped under it verbatim
    for r in rows:
        d = parse_date(r["date"])
        if d is None:
            unparsable.add(r["date"])
        buckets[period_key(d, by) if d else r["date"]].append(r)
    groups = []
    for key in sorted(buckets, reverse=True):
        members = sorted(buckets[key], key=lambda r: (r["date"], r["id"]), reverse=True)
        summary = _summarise(members)
        label = key if key in unparsable else period_label(key, by)
        summary.update(key=key, label=label, rows=members)
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


def overview(all_rows: list[dict], today: date, range_key: str, by: str) -> dict:
    rows = filter_range(all_rows, today, range_key)
    start = range_start(today, range_key)
    totals = _summarise(rows)

    # Same-length window immediately before this one, for the deltas.
    previous = None
    if start is not None:
        days = RANGES[range_key] or 0
        prev_lo, prev_hi = (start - timedelta(days=days)).isoformat(), start.isoformat()
        previous = _summarise([r for r in all_rows if prev_lo <= r["date"] < prev_hi])

    # Activity per period, zero-filled across the whole range.
    first = min((parse_date(r["date"]) for r in rows if parse_date(r["date"])), default=None)
    chart_start = start or first
    by_period: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = parse_date(r["date"])
        if d:
            by_period[period_key(d, by)].append(r)
    activity = []
    if chart_start is not None:
        for key in period_keys(chart_start, today, by):
            s = _summarise(by_period.get(key, []))
            activity.append({"key": key, "label": period_short(key, by), **s})

    # Calendar heatmap: sessions per day, Monday-aligned weeks ending today.
    heat_start = chart_start or today
    heat_start = max(heat_start, today - timedelta(weeks=HEATMAP_MAX_WEEKS - 1))
    heat_start -= timedelta(days=heat_start.weekday())
    per_day = Counter(r["date"] for r in rows)
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
        weights = [(weight_number(r["weight"]), r["weight"]) for r in members]
        weights = [w for w in weights if w[0] is not None]
        top.append(
            {
                "exercise": name,
                "entries": len(members),
                "sessions": len({r["date"] for r in members}),
                "best": max(weights)[1] if weights else "",
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
            for k in ("sessions", "entries", "volume")
        },
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
