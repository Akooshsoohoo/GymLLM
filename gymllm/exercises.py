"""Canonical exercise list, matching, and LLM tag fallback."""

from __future__ import annotations

import csv
import difflib
import re
from collections import Counter
from pathlib import Path

from .llm.client import LLMError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "taggedExerciseList.csv"
ACTIVITY_PATH = DATA_DIR / "activityList.csv"

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _norm(name: str | None) -> str:
    return _WS_RE.sub(" ", (name or "").strip().lower())


# Words that vary an exercise without making it a different movement: how it is set
# up, then what it is done with. A name the list does not have, built from a listed
# movement and these words ("kettlebell bulgarian split squat"), still matches. The
# order here is the order they lead a composed name.
SETUPS = (
    "singlearm", "singleleg", "alternating", "seated", "standing", "kneeling", "lying",
    "prone", "incline", "decline", "chestsupported", "deficit", "wide", "close", "neutral",
    "underhand", "overhand", "highbar", "lowbar", "weighted", "bodyweight", "assisted",
)  # fmt: skip
EQUIPMENT = (
    "barbell", "dumbbell", "kettlebell", "cable", "machine", "smith", "ezbar", "trapbar",
    "safetybar", "swissbar", "band", "landmine", "plate", "medball", "stabilityball", "bosu",
    "trx", "ring", "sandbag", "rope", "vbar", "straightbar",
)  # fmt: skip
VARIATIONS = SETUPS + EQUIPMENT
_VARIATION_SET = frozenset(VARIATIONS)

# How a joined-up word reads in a name.
_DISPLAY = {
    "singlearm": "single arm", "singleleg": "single leg", "chestsupported": "chest-supported",
    "highbar": "high bar", "lowbar": "low bar", "smith": "smith machine", "ezbar": "ez bar",
    "trapbar": "trap bar", "safetybar": "safety bar", "swissbar": "swiss bar",
    "medball": "medicine ball", "stabilityball": "stability ball", "vbar": "v-bar",
    "straightbar": "straight bar", "pullup": "pull-up", "chinup": "chin-up",
    "pushup": "push-up", "situp": "sit-up", "stepup": "step-up", "stepdown": "step-down",
    "muscleup": "muscle-up", "getup": "get-up", "pullapart": "pull-apart",
    "pullthrough": "pull-through", "tbar": "t-bar", "stiffleg": "stiff leg",
    "battlerope": "battle rope", "ropeclimb": "rope climb", "sidelying": "side-lying",
}  # fmt: skip

# Spellings, abbreviations and nicknames, rewritten in this order before a name is
# split into words. Anything that makes one word of two gets an entry in _DISPLAY.
_PHRASES = [
    (re.compile(rf"\b(?:{pattern})\b"), repl)
    for pattern, repl in (
        (r"ohp|military press", "overhead press"),
        (r"rdls?", "romanian deadlift"),
        (r"sldls?|(?:stiff|straight) leg(?:ged)? deadlifts?", "stiffleg deadlift"),
        (r"bss|rfess|rear foot elevated split squats?", "bulgarian split squat"),
        (r"cgbp", "close bench press"),
        (r"ghr", "glute ham raise"),
        (r"hspu", "handstand pushup"),
        (r"t2b|ttb", "toes to bar"),
        (r"c2b", "chest to bar pullup"),
        (r"tgu", "turkish getup"),
        (r"lying triceps? extensions?", "skullcrusher"),
        (r"french press", "overhead triceps extension"),
        (r"hamstring curls?", "leg curl"),
        (r"touch and go|tng", ""),
        (r"low to high", "low"),
        (r"high to low", "high"),
        (r"side ?lying", "sidelying"),
        (r"(?:side|lat) (?:lateral )?raises?", "lateral raise"),
        (r"farmers? walks?", "farmers carry"),
        (r"wood ?chop(?:per)?s?", "woodchopper"),
        (r"biceps? curls?", "curl"),
        (r"triceps? (?:push|press) ?downs?", "pushdown"),
        (r"pull ?ups?", "pullup"),
        (r"chin ?ups?", "chinup"),
        (r"(?:push|press) ?ups?", "pushup"),
        (r"sit ?ups?", "situp"),
        (r"step ?ups?", "stepup"),
        (r"step ?downs?", "stepdown"),
        (r"muscle ?ups?", "muscleup"),
        (r"get ?ups?", "getup"),
        (r"pull ?downs?", "pulldown"),
        (r"(?:push|press) ?downs?", "pushdown"),
        (r"pull ?overs?", "pullover"),
        (r"pull ?aparts?", "pullapart"),
        (r"pull ?throughs?", "pullthrough"),
        (r"kick ?backs?", "kickback"),
        (r"dead ?lifts?", "deadlift"),
        (r"skull ?crushers?", "skullcrusher"),
        (r"roll ?outs?", "rollout"),
        (r"battle ?ropes?", "battlerope"),
        (r"rope ?climbs?", "ropeclimb"),
        (r"t ?bar", "tbar"),
        (r"e ?z(?: curl)? ?bars?|ez", "ezbar"),
        (r"(?:trap|hex) ?bars?", "trapbar"),
        (r"v ?(?:bar|handle)", "vbar"),
        (r"straight ?bar", "straightbar"),
        (r"safety(?: squat)? ?bar|ssb(?: bar)?", "safetybar"),
        (r"(?:swiss|football|multi grip) bar", "swissbar"),
        (r"smith(?: machine)?", "smith"),
        (r"plate loaded|hammer strength|iso ?lateral|selectorized|pin loaded", "machine"),
        (r"body ?weight|bw", "bodyweight"),
        (r"kettle ?bells?|kbs?", "kettlebell"),
        (r"dumb ?bells?|dbs?", "dumbbell"),
        (r"bar ?bells?|bb", "barbell"),
        (r"med(?:icine)? ?balls?", "medball"),
        (r"(?:stability|swiss|exercise|physio) ?balls?", "stabilityball"),
        (r"bosu(?: ball)?", "bosu"),
        (r"(?:resistance |mini |loop )?bands?|banded", "band"),
        (r"suspension(?: trainer)?", "trx"),
        (r"(?:gymnastics? )?rings?", "ring"),
        (r"land ?mine", "landmine"),
        (r"(?:one|1|single|unilateral) ?(?:arm(?:ed)?|hand(?:ed)?)", "singlearm"),
        (r"(?:one|1|single) ?leg(?:ged)?", "singleleg"),
        (r"alternat(?:e|ing)", "alternating"),
        (r"(?:half|tall) kneeling", "kneeling"),
        (r"laying", "lying"),
        (r"chest supported", "chestsupported"),
        (r"bent ?over", ""),
        (r"high ?bar", "highbar"),
        (r"low ?bar", "lowbar"),
        (r"narrow", "close"),
        (r"supinated", "underhand"),
        (r"pronated", "overhand"),
        (r"(?:chest )?fl(?:ys?|yes?|ies)", "fly"),
        (r"calves", "calf"),
        (r"abs|abdominals?", "ab"),
    )
]

# Words that say nothing about which exercise it is: filler, the default way of doing
# a lift, and how a set was performed (which belongs in the notes).
_STOPWORDS = frozenset(
    "with w the a an on of to and in for using at from grip stance attachment handle flat "
    "conventional regular normal standard traditional strict style variation "
    "pause paused tempo slow controlled heavy light".split()
)


def _stem(token: str) -> str:
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-2] if token.endswith(("ches", "shes", "sses", "xes")) else token[:-1]
    return token


def _words(name: str | None) -> list[str]:
    """A name as plain words, with spellings and nicknames rewritten."""
    text = _PUNCT_RE.sub(" ", _norm(name).replace("'", "").replace("’", "")).strip()
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    return text.split()


def _key(name: str | None) -> frozenset[str]:
    """What a name says, whatever its word order, spelling or filler."""
    return frozenset(_stem(w) for w in _words(name) if w not in _STOPWORDS)


def _movement(name: str) -> str:
    """A name without its setup and equipment words: 'incline dumbbell bench press'
    -> 'bench press'."""
    out: list[str] = []
    dropped = False
    for word in _words(name):
        if _stem(word) in _VARIATION_SET or (dropped and word in ("grip", "stance")):
            dropped = True
            continue
        dropped = False
        out.append(_DISPLAY.get(word, word))
    return " ".join(out)


def _variation_text(tokens) -> str:
    return " ".join(_DISPLAY.get(t, t) for t in VARIATIONS if t in tokens)


def load_exercises(path: Path = DATA_PATH) -> list[tuple[str, str, list[str]]]:
    """(name, tags, aliases) per row, in file order: where two names fit equally well,
    the one listed first wins."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            (
                _norm(row["exercise"]),
                (row.get("tags") or "").strip(),
                [a for a in map(_norm, (row.get("aliases") or "").split(";")) if a],
            )
            for row in reader
            if row.get("exercise")
        ]


def load_activities(path: Path = ACTIVITY_PATH) -> list[str]:
    """Cardio and sport names, as they are suggested when logging by hand."""
    with open(path, newline="", encoding="utf-8") as f:
        return [row["activity"].strip() for row in csv.DictReader(f) if row.get("activity")]


EXERCISES = load_exercises()
EXERCISE_NAMES = [name for name, _, _ in EXERCISES]
ACTIVITY_NAMES = load_activities()
_TAGS = {name: tags for name, tags, _ in EXERCISES}
_KEYS = {name: _key(name) for name in EXERCISE_NAMES}
_MOVEMENT_KEYS = {name: _KEYS[name] - _VARIATION_SET for name in EXERCISE_NAMES}
# Every way of saying a listed exercise -> its name. Names go in before aliases, so a
# nickname never takes over another exercise's own name.
_BY_KEY: dict[frozenset[str], str] = {}
for _name in EXERCISE_NAMES:
    _BY_KEY.setdefault(_KEYS[_name], _name)
for _name, _, _aliases in EXERCISES:
    for _alias in _aliases:
        _BY_KEY.setdefault(_key(_alias), _name)
_VOCAB = _VARIATION_SET.union(*_BY_KEY)
_VOCAB_LIST = sorted(_VOCAB)
_MOVEMENT_WORDS = _VOCAB - _VARIATION_SET


def _movements() -> list[str]:
    """Each movement once. One the list has in a single form keeps its whole name:
    'sandbag to shoulder' says more than 'to shoulder'."""
    forms = Counter(_MOVEMENT_KEYS.values())
    seen: set[frozenset[str]] = set()
    out: list[str] = []
    for name in EXERCISE_NAMES:
        movement = _MOVEMENT_KEYS[name]
        if movement and movement not in seen:
            seen.add(movement)
            out.append(_movement(name) if forms[movement] > 1 else name)
    return out


MOVEMENT_NAMES = _movements()


def exercise_list_text() -> str:
    """The movements the list knows, for the parsing prompt. The full list is every
    movement in several setups and with several pieces of equipment, which is far too
    long to send with each request, so the prompt gets the movements and the words."""
    return ", ".join(MOVEMENT_NAMES)


def setup_text() -> str:
    return ", ".join(_DISPLAY.get(t, t) for t in SETUPS)


def equipment_text() -> str:
    return ", ".join(_DISPLAY.get(t, t) for t in EQUIPMENT)


def _raw_key(raw: str) -> frozenset[str]:
    """_key, with each word the list has never seen swapped for a near miss it has."""
    key = set()
    for word in _words(raw):
        if word in _STOPWORDS:
            continue
        token = _stem(word)
        if token not in _VOCAB and len(word) > 3:
            close = difflib.get_close_matches(word, _VOCAB_LIST, n=1, cutoff=0.8)
            token = close[0] if close else token
        key.add(token)
    return frozenset(key)


def _tags_for(name: str, variations) -> str:
    tags = _TAGS[name]
    one_sided = "singlearm" in variations or "singleleg" in variations
    return f"{tags};unilateral" if one_sided and "unilateral" not in tags.split(";") else tags


def match_exercise(raw: str | None) -> tuple[str, str] | None:
    """Map a free-text exercise name to (name, tags), or None.

    Order: the same words as a listed name or alias, in any order and with typos
    fixed -> a listed name is contained in the raw name (prefer the most specific).
    Setup and equipment words left over are kept, so 'seated cable lateral raise'
    stays its own exercise with the cable lateral raise's tags; a left-over word
    that names another movement rules the match out, so 'romanian deadlift' is never
    a deadlift -> all of the raw name's words appear in a listed name (prefer the
    fewest extra words) -> a listed movement with different equipment or setup,
    named as typed.
    """
    raw = _norm(raw)
    if not raw:
        return None
    if raw in _TAGS:
        return raw, _TAGS[raw]

    key = _raw_key(raw)
    if not key:
        return None
    if key in _BY_KEY:
        name = _BY_KEY[key]
        return name, _TAGS[name]

    contained = [
        n for n in EXERCISE_NAMES if _KEYS[n] <= key and not (key - _KEYS[n]) & _MOVEMENT_WORDS
    ]
    if contained:
        best = max(contained, key=lambda n: len(_KEYS[n]))
        extra = (key - _KEYS[best]) & _VARIATION_SET
        if not extra:
            return best, _TAGS[best]
        return f"{_variation_text(extra)} {best}", _tags_for(best, extra)

    containing = [n for n in EXERCISE_NAMES if key <= _KEYS[n]]
    if containing:
        best = min(containing, key=lambda n: len(_KEYS[n]))
        return best, _TAGS[best]

    variations = key & _VARIATION_SET
    movement = key - variations
    same = [n for n in EXERCISE_NAMES if movement and _MOVEMENT_KEYS[n] == movement]
    if same:
        best = max(same, key=lambda n: len(_KEYS[n] & variations))
        return f"{_variation_text(variations)} {_movement(best)}", _tags_for(best, variations)
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
