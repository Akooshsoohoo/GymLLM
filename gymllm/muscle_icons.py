"""Which muscle icon stands for a day: static/muscle-icons.js's forTags(), for the iOS
app, which ships the icons as images and cannot run that script. Keep the two in step:
tests/test_muscle_icons.py compares them when a JavaScript runner is around.

    python ios/scripts/muscle_icons.py     # redraw the app's images after a change
"""

from __future__ import annotations

import re

GROUPS = (
    "chest", "back", "shoulders", "arms", "triceps", "core", "legs", "glutes", "hamstrings",
    "upper", "lower", "push", "pull", "full", "cardio",
)  # fmt: skip
ACTIVITIES = (
    "run", "walk", "hike", "cycle", "swim", "row", "climb", "yoga", "pilates", "hiit",
    "jumprope", "stairs", "boxing", "martial", "basketball", "soccer", "tennis", "paddle",
    "golf", "baseball", "volleyball", "football", "hockey", "ski", "dance", "sport",
)  # fmt: skip
ALIAS = {
    "pecs": "chest", "lats": "back", "delts": "shoulders", "biceps": "arms", "abs": "core",
    "quads": "legs", "glute": "glutes", "hams": "hamstrings", "upper body": "upper",
    "lower body": "lower", "full body": "full", "bike": "cycle", "cycling": "cycle",
    "pickleball": "paddle", "padel": "paddle",
}  # fmt: skip
# Free text -> id. First match wins, so specific phrases sit above broad ones.
WORDS = [
    (re.compile(pattern), icon)
    for pattern, icon in (
        (r"pickle|padel|paddle ?ball", "paddle"),
        (r"tennis|squash|racquet|badminton", "tennis"),
        (r"basketball|hoops|shoot ?around", "basketball"),
        (r"soccer|futsal|footy", "soccer"),
        (r"american football|flag football|\bfootball\b", "football"),
        (r"volleyball", "volleyball"),
        (r"baseball|softball|batting cage", "baseball"),
        (r"golf|driving range", "golf"),
        (r"hockey|lacrosse", "hockey"),
        (r"\bski(ing|s)?\b|snowboard|\bsnow", "ski"),
        (r"boxing|kickbox|sparring|heavy bag|\bbox\b(?! ?jump)", "boxing"),
        (r"jiu|bjj|judo|karate|muay|mma|taekwondo|wrestl|martial", "martial"),
        (r"dance|zumba|barre", "dance"),
        (r"pilates|reformer", "pilates"),
        (r"yoga|stretch|mobility|flexib", "yoga"),
        (r"climb|boulder", "climb"),
        (r"hike|hiking|trail|ruck", "hike"),
        (r"swim|laps? in the pool|pool", "swim"),
        (r"rowing|\berg\b|rower|kayak|canoe|paddle ?board", "row"),
        (r"bike|cycl|spin|peloton", "cycle"),
        (r"jump ?rope|skipping", "jumprope"),
        (r"stair|stepmill|step ?machine|elliptical", "stairs"),
        (r"hiit|box jump|plyo|circuit|crossfit|bootcamp|tabata|burpee|emom|amrap|wod", "hiit"),
        (r"\bran\b|\brun|jog|sprint|treadmill|marathon|\d+ ?k\b", "run"),
        (r"walk|steps|stroll", "walk"),
        (r"hip thrust|glute bridge|kickback|glute", "glutes"),
        (r"rdl|romanian|leg curl|hamstring|good morning", "hamstrings"),
        (r"squat|lunge|leg press|leg extension|calf|split squat|step ?up|quad|\blegs?\b", "legs"),
        (r"bench|chest|fly|flye|push ?-?up|dip|pec", "chest"),
        (r"deadlift|pull ?-?up|chin ?-?up|lat |pulldown|\brows?\b|back", "back"),
        (r"overhead|ohp|shoulder|lateral raise|military|arnold|delt", "shoulders"),
        (r"tricep|skull ?crusher|pushdown", "triceps"),
        (r"curl|bicep|forearm|arm", "arms"),
        (r"plank|crunch|sit ?-?up|ab |abs|core|hollow|russian twist|leg raise", "core"),
        (r"push day", "push"),
        (r"pull day", "pull"),
        (r"upper", "upper"),
        (r"lower", "lower"),
        (r"full body|total body", "full"),
        (r"cardio|conditioning", "cardio"),
        (r"sport|game|match|practice|league", "sport"),
    )
]
UPPER = ("chest", "back", "shoulders", "arms", "triceps")
LOWER = ("legs", "glutes", "hamstrings")
_SPLIT = re.compile(r"[,;\n]| and | then ")


def resolve(text: str) -> str | None:
    padded = f" {text.lower()} "
    return next((icon for pattern, icon in WORDS if pattern.search(padded)), None)


def _norm(word: str) -> str:
    key = word.lower().strip()
    if key in GROUPS or key in ACTIVITIES:
        return key
    return ALIAS.get(key) or resolve(key) or "full"


def for_tags(hint: str) -> str:
    """One icon id for a day, from session_meta.icon_hint(): tags or free text."""
    found = [_norm(word) for word in _SPLIT.split(hint or "") if word.strip()]
    acts = list(dict.fromkeys(k for k in found if k in ACTIVITIES))
    up = [g for g in UPPER if g in found]
    lo = [g for g in LOWER if g in found]
    if up and lo:
        return "full"
    if len(up) == 1 and not lo:
        return up[0]
    if len(lo) == 1 and not up:
        return lo[0]
    if lo:
        return "lower"
    if up:
        if all(g in ("chest", "shoulders", "triceps") for g in up):
            return "push"
        return "pull" if all(g in ("back", "arms") for g in up) else "upper"
    if len(acts) == 1:
        return acts[0]
    if len(acts) > 1:
        return "cardio"
    if "core" in found:
        return "core"
    return "cardio" if "cardio" in found else "full"
