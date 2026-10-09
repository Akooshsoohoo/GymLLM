import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gymllm import muscle_icons

ROOT = Path(__file__).resolve().parents[1]
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"

HINTS = [
    "",
    "chest",
    "chest, shoulders",
    "chest, triceps, shoulders",
    "back, arms",
    "chest, back",
    "legs",
    "legs, glutes",
    "chest, legs",
    "core",
    "core, cardio",
    "run",
    "run, swim",
    "chest, run",
    "pickup basketball",
    "box jumps",
    "boxing",
    "ran 5k",
    "walk",
    "yoga and stretching",
    "barbell bench press",
    "romanian deadlift",
    "deadlift",
    "biceps",
    "abs",
    "full body",
    "kettlebell swing",
    "pull ups then dips",
    "hike; kayak",
    "something nobody has heard of",
]


def js_runner():
    node = shutil.which("node")
    if node:
        return [
            node,
            "-e",
        ], "const M = require('./static/muscle-icons.js'); const print = console.log;"
    if Path(JSC).exists():
        return [JSC, "-e"], "load('static/muscle-icons.js'); const M = MuscleIcons;"
    return None, None


def run_js(body: str):
    command, head = js_runner()
    if command is None:
        pytest.skip("no JavaScript runner (node, or macOS's jsc)")
    out = subprocess.run(
        [*command, f"{head} {body}"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


@pytest.mark.parametrize(
    "hint,icon",
    [
        ("chest", "chest"),
        ("chest, shoulders", "push"),
        ("back, arms", "pull"),
        ("chest, back", "upper"),
        ("legs, glutes", "lower"),
        ("chest, legs", "full"),
        ("run", "run"),
        ("run, swim", "cardio"),
        ("chest, run", "chest"),
        ("barbell bench press", "chest"),
        ("box jumps", "hiit"),
        ("", "full"),
    ],
)
def test_for_tags(hint, icon):
    assert muscle_icons.for_tags(hint) == icon


def test_for_tags_matches_the_browsers():
    theirs = run_js(f"print(JSON.stringify({json.dumps(HINTS)}.map(h => M.forTags(h))));")
    assert [muscle_icons.for_tags(h) for h in HINTS] == theirs


def test_the_same_icons_as_the_browser():
    ids = run_js("print(JSON.stringify([M.groups.map(g => g.id), M.activities.map(a => a.id)]));")
    assert [list(muscle_icons.GROUPS), list(muscle_icons.ACTIVITIES)] == ids
