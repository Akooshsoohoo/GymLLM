"""Turn free-text workout descriptions into normalised log entries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .exercises import exercise_list_text
from .llm.client import BadOutputError

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM_PROMPT = """You are a workout log parser. Convert natural-language gym logs into structured JSON.

Today is {weekday}, {today}.

OUTPUT: Return ONLY a JSON object with this shape, no markdown, no explanation:
{{"date": "YYYY-MM-DD" or null,
 "exercises": [{{"exercise": "barbell bench press", "weight": "185 lbs", "sets": 3, "reps": [10, 10, 10], "notes": ""}}],
 "cardio": [{{"activity": "walking", "distance": "3 miles", "duration": "45 min", "notes": ""}}],
 "bodyweight": "130 lbs" or null}}

One message can contain any mix of the three. Put each piece where it belongs:
  "exercises" - lifts and strength/bodyweight exercises done in sets and reps (bench, curls, pull ups, squats, planks).
  "cardio"    - activities measured by distance or time (walk, run, jog, hike, swim, bike/cycle, rowing machine, elliptical, stair climber, jump rope, sports). Never put these in "exercises".
  "bodyweight" - what the person weighs, if they say it ("weighed in at 130", "I'm 82 kg"). This is the person's body weight, never an exercise weight.
Leave "exercises" or "cardio" as [] and "bodyweight" as null when that kind of thing is not mentioned.

DATE:
  If the text says when the workout happened ("yesterday", "on Monday", "last Friday", "2025-06-01"), resolve it relative to today and put it in "date".
  If no day is mentioned, "date" must be null.

SETS & REPS - interpret shorthand as follows:
  '5x5'        -> sets: 5, reps: [5,5,5,5,5]
  '3x10'       -> sets: 3, reps: [10,10,10]
  '10,8,6'     -> sets: 3, reps: [10,8,6]
  'sets of 12' (no count given) -> assume 3 sets -> sets: 3, reps: [12,12,12]
  'a few sets' -> assume 3 sets
  only reps mentioned, no sets -> assume 1 set
  no reps or sets mentioned -> sets: null, reps: null

WEIGHT:
  Include units if stated ('185 lbs', '80 kg'). Keep the unit the user used.
  A bare number next to the exercise is the weight ('bench 185 5x5' -> weight: "185"); keep it as written, do not invent a unit.
  'bodyweight' or 'BW' -> weight: "bodyweight".
  Not mentioned -> weight: "".

NOTES: anything that is not exercise/weight/sets/reps (e.g. "felt easy", "paused reps"). Otherwise "".

CARDIO entries: "activity" is a short lowercase name (walking, running, swimming, cycling, hiking, rowing, elliptical).
  "distance" and "duration" are strings with the unit exactly as the person wrote it ("3 miles", "5 km", "45 min", "1 h 20 min"); "" when not given.
  "notes" for pace, route, how it felt; otherwise "".

BODY WEIGHT: keep the unit as written ("130 lbs", "82 kg"); a bare number stays a bare number ("130").

ASSUMPTIONS - always assume rather than ask:
  Unclear equipment -> pick the most common variant (usually barbell for compounds, dumbbell for isolation).
  Unclear weight -> leave blank. Unclear reps -> use the most reasonable default for that exercise.

EXERCISE NAMES - use a name from this list when one fits; only invent a name if nothing fits:
{exercise_list}

Each "exercises" entry must have exactly these keys: exercise, weight, sets, reps, notes.
sets is an integer or null. reps is a list of integers (one per set) or null. All others are strings.
Each "cardio" entry must have exactly these keys: activity, distance, duration, notes (all strings).
Return ONLY the JSON object."""


@dataclass
class ParsedWorkout:
    date: str | None
    entries: list[dict] = field(default_factory=list)
    cardio: list[dict] = field(default_factory=list)
    bodyweight: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.entries or self.cardio or self.bodyweight)


def build_system_prompt(today: date) -> str:
    return SYSTEM_PROMPT.format(
        today=today.isoformat(),
        weekday=today.strftime("%A"),
        exercise_list=exercise_list_text(),
    )


def is_iso_date(value) -> bool:
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _to_int_str(value) -> str:
    if value is None or value == "" or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(int(value))
    text = str(value).strip()
    if re.match(r"^-?\d+(?:\.\d+)?$", text):
        return str(int(float(text)))
    return text


def _weight_str(weight) -> str:
    if weight is None or isinstance(weight, bool):
        return ""
    if isinstance(weight, float):
        return f"{weight:g}"
    return str(weight).strip()


def normalize_entry(entry) -> dict:
    """Coerce an LLM entry into flat strings suitable for the String columns."""
    if not isinstance(entry, dict):
        raise BadOutputError("The model returned an entry that is not an object.")

    reps = entry.get("reps")
    if isinstance(reps, list):
        parts = [_to_int_str(r) for r in reps if r is not None and r != ""]
        reps_str = ", ".join(p for p in parts if p)
    else:
        reps_str = _to_int_str(reps)

    return {
        "exercise": str(entry.get("exercise") or "").strip().lower(),
        "weight": _weight_str(entry.get("weight")),
        "sets": _to_int_str(entry.get("sets")),
        "reps": reps_str,
        "notes": str(entry.get("notes") or "").strip(),
    }


def _text(value) -> str:
    """A model value as the string a person would have typed: 3.0 -> '3', None -> ''."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value).strip()


def normalize_cardio(entry) -> dict:
    """Coerce a cardio entry into flat strings."""
    if not isinstance(entry, dict):
        raise BadOutputError("The model returned a cardio entry that is not an object.")
    return {
        "activity": str(entry.get("activity") or "").strip().lower(),
        "distance": _text(entry.get("distance")),
        "duration": _text(entry.get("duration")),
        "notes": str(entry.get("notes") or "").strip(),
    }


def parsed_from_output(data) -> ParsedWorkout:
    """Validate and normalise a decoded model response."""
    if isinstance(data, list):
        data = {"exercises": data, "date": None}
    if not isinstance(data, dict):
        raise BadOutputError("The model did not return a JSON object.")
    exercises = data.get("exercises")
    cardio = data.get("cardio")
    bodyweight = data.get("bodyweight")
    if not isinstance(exercises, list) and not isinstance(cardio, list) and bodyweight is None:
        raise BadOutputError("The model did not return an 'exercises' list.")
    exercises = exercises if isinstance(exercises, list) else []
    cardio = cardio if isinstance(cardio, list) else []
    entries = [normalize_entry(e) for e in exercises if isinstance(e, dict)]
    entries = [e for e in entries if e["exercise"]]
    if exercises and not entries:
        raise BadOutputError("The model returned entries without exercise names.")
    activities = [normalize_cardio(c) for c in cardio if isinstance(c, dict)]
    activities = [c for c in activities if c["activity"]]
    when = data.get("date")
    return ParsedWorkout(
        date=when if is_iso_date(when) else None,
        entries=entries,
        cardio=activities,
        bodyweight=_text(bodyweight),
    )


def parse_workout(text: str, client, today: date | None = None) -> ParsedWorkout:
    """Parse `text` with `client`, retrying once if the output is unusable."""
    today = today or date.today()
    system = build_system_prompt(today)
    last: BadOutputError | None = None
    for _ in range(2):
        try:
            return parsed_from_output(client.complete_json(system, text))
        except BadOutputError as e:
            last = e
    assert last is not None
    raise last
