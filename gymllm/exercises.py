"""Canonical exercise list, matching, and LLM tag fallback."""

from __future__ import annotations

import csv
import difflib
import re
from pathlib import Path

from .llm.client import LLMError

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "taggedExerciseList.csv"

_WS_RE = re.compile(r"\s+")


def _norm(name: str | None) -> str:
    return _WS_RE.sub(" ", (name or "").strip().lower())


def load_exercises(path: Path = DATA_PATH) -> list[tuple[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            (_norm(row["exercise"]), (row.get("tags") or "").strip())
            for row in reader
            if row.get("exercise")
        ]


EXERCISES = load_exercises()
EXERCISE_NAMES = [name for name, _ in EXERCISES]
_TAGS = dict(EXERCISES)
_TOKENS = {name: set(name.split()) for name in EXERCISE_NAMES}


def exercise_list_text() -> str:
    return ", ".join(EXERCISE_NAMES)


def match_exercise(raw: str | None) -> tuple[str, str] | None:
    """Map a free-text exercise name to (canonical name, tags), or None.

    Order: exact -> fuzzy (typos) -> a canonical name is contained in the raw
    name as whole words (prefer the most specific) -> all of the raw name's
    words appear in a canonical name (prefer the fewest extra words).
    """
    raw = _norm(raw)
    if not raw:
        return None
    if raw in _TAGS:
        return raw, _TAGS[raw]

    close = difflib.get_close_matches(raw, EXERCISE_NAMES, n=1, cutoff=0.85)
    if close:
        return close[0], _TAGS[close[0]]

    raw_tokens = set(raw.split())
    contained = [n for n in EXERCISE_NAMES if _TOKENS[n] <= raw_tokens]
    if contained:
        best = max(contained, key=lambda n: len(_TOKENS[n]))
        return best, _TAGS[best]

    containing = [n for n in EXERCISE_NAMES if raw_tokens <= _TOKENS[n]]
    if containing:
        best = min(containing, key=lambda n: (len(_TOKENS[n]), n))
        return best, _TAGS[best]
    return None


TAG_SYSTEM = (
    "You assign muscle-group and movement-type tags to gym exercises. "
    'Reply with a JSON object: {"tags": ["back", "pull", "compound", "lats"]}. '
    "Use short lowercase tags such as chest, back, shoulders, biceps, triceps, quads, "
    "hamstrings, glutes, core, push, pull, compound, isolation, upper, lower."
)


def clean_tags(tags) -> str:
    """Normalise a list (or ';'/',' separated string) of tags into 'a;b;c'."""
    if isinstance(tags, str):
        tags = re.split(r"[;,]", tags)
    if not isinstance(tags, list):
        return ""
    clean: list[str] = []
    for t in tags:
        t = _norm(str(t))
        if t and t not in clean:
            clean.append(t)
    return ";".join(clean)


def llm_tags(raw: str, client) -> str:
    """Ask the LLM for tags for an exercise not in the list. Empty string on failure."""
    try:
        data = client.complete_json(TAG_SYSTEM, f"Exercise: {raw}")
    except LLMError:
        return ""
    return clean_tags(data.get("tags") if isinstance(data, dict) else None)
