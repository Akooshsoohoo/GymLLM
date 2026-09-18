from datetime import date

import pytest

from gymllm.llm.client import BadOutputError, extract_json
from gymllm.parsing import (
    build_system_prompt,
    is_iso_date,
    normalize_cardio,
    normalize_entry,
    parse_workout,
    parsed_from_output,
)
from tests.conftest import FakeLLM


def test_prompt_contains_today_and_weekday():
    prompt = build_system_prompt(date(2026, 9, 14))
    assert "2026-09-14" in prompt
    assert "Monday" in prompt
    assert "barbell bench press" in prompt  # exercise list is injected


def test_prompt_default_unit_defaults_to_lbs_and_is_overridable():
    assert 'weight: "185 lbs"' in build_system_prompt(date(2026, 9, 14))
    assert 'weight: "185 kg"' in build_system_prompt(date(2026, 9, 14), default_unit="kg")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-01-05", True),
        ("2026-13-05", False),
        ("yesterday", False),
        (None, False),
        ("2026-1-5", False),
    ],
)
def test_is_iso_date(value, expected):
    assert is_iso_date(value) is expected


def test_normalize_entry_flattens_types():
    entry = normalize_entry(
        {
            "exercise": " Barbell Bench Press ",
            "weight": 185,
            "sets": 3,
            "reps": [10, 8, 6],
            "notes": None,
        }
    )
    assert entry == {
        "exercise": "barbell bench press",
        "weight": "185",
        "sets": "3",
        "reps": "10, 8, 6",
        "notes": "",
    }


def test_normalize_entry_handles_nulls_and_strings():
    entry = normalize_entry(
        {"exercise": "squat", "weight": "bodyweight", "sets": None, "reps": "12", "notes": "easy"}
    )
    assert entry["sets"] == ""
    assert entry["reps"] == "12"
    assert entry["weight"] == "bodyweight"
    assert (
        normalize_entry({"exercise": "x", "sets": "4.0", "reps": ["5", 5.0, None]})["reps"]
        == "5, 5"
    )
    assert normalize_entry({"exercise": "x", "sets": "4.0"})["sets"] == "4"


def test_normalize_entry_rejects_non_dict():
    with pytest.raises(BadOutputError):
        normalize_entry(["not", "a", "dict"])


def test_parse_workout_returns_date_and_entries():
    llm = FakeLLM().queue(
        {
            "date": "2026-09-13",
            "exercises": [
                {
                    "exercise": "barbell bench press",
                    "weight": "185 lbs",
                    "sets": 5,
                    "reps": [5] * 5,
                    "notes": "",
                }
            ],
        }
    )
    parsed = parse_workout("bench 185 5x5 yesterday", llm, today=date(2026, 9, 14))
    assert parsed.date == "2026-09-13"
    assert parsed.entries[0]["reps"] == "5, 5, 5, 5, 5"
    assert "2026-09-14" in llm.calls[0][0]


def test_parse_workout_threads_default_unit_into_the_prompt():
    llm = FakeLLM().queue({"date": None, "exercises": []})
    parse_workout("curled the 20s", llm, today=date(2026, 9, 14), default_unit="kg")
    assert 'weight: "185 kg"' in llm.calls[0][0]


def test_parse_workout_accepts_bare_list_and_ignores_bad_date():
    llm = FakeLLM().queue([{"exercise": "squat", "sets": 3, "reps": [5, 5, 5]}])
    parsed = parse_workout("squats", llm)
    assert parsed.date is None
    assert parsed.entries[0]["exercise"] == "squat"

    llm = FakeLLM().queue({"date": "last tuesday", "exercises": [{"exercise": "squat"}]})
    assert parse_workout("squats", llm).date is None


def test_parse_workout_retries_once_on_bad_output():
    llm = FakeLLM().queue({"nope": 1}, {"date": None, "exercises": [{"exercise": "row"}]})
    parsed = parse_workout("rows", llm)
    assert parsed.entries[0]["exercise"] == "row"
    assert len(llm.calls) == 2


def test_parse_workout_raises_after_two_bad_outputs():
    llm = FakeLLM().queue({"nope": 1}, "still nope")
    with pytest.raises(BadOutputError):
        parse_workout("rows", llm)


def test_parse_workout_rejects_entries_without_names():
    llm = FakeLLM().queue({"exercises": [{"weight": "10"}]}, {"exercises": [{"weight": "10"}]})
    with pytest.raises(BadOutputError):
        parse_workout("???", llm)


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here you go:\n{"a": [1, 2]}\nHope that helps.', {"a": [1, 2]}),
        ("[1, 2]", [1, 2]),
    ],
)
def test_extract_json_variants(text, expected):
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", "{broken", None])
def test_extract_json_failures(text):
    with pytest.raises(BadOutputError):
        extract_json(text)


# --- cardio and body weight ---------------------------------------------------


def test_prompt_describes_cardio_and_bodyweight():
    prompt = build_system_prompt(date(2026, 9, 14))
    assert '"cardio"' in prompt and '"bodyweight"' in prompt
    assert "never an exercise weight" in prompt


def test_normalize_cardio():
    assert normalize_cardio(
        {"activity": " Walking ", "distance": 3.0, "duration": "45 min", "notes": None}
    ) == {"activity": "walking", "distance": "3", "duration": "45 min", "notes": ""}
    with pytest.raises(BadOutputError):
        normalize_cardio("walk")


def test_parsed_from_output_splits_the_three_kinds():
    parsed = parsed_from_output(
        {
            "date": None,
            "exercises": [
                {
                    "exercise": "pull up",
                    "weight": "bodyweight",
                    "sets": None,
                    "reps": None,
                    "notes": "",
                },
                {
                    "exercise": "dumbbell bicep curl",
                    "weight": "20 lb",
                    "sets": 3,
                    "reps": [10, 10, 10],
                    "notes": "",
                },
            ],
            "cardio": [{"activity": "walking", "distance": "3 miles", "duration": "", "notes": ""}],
            "bodyweight": "130 lbs",
        }
    )
    assert [e["exercise"] for e in parsed.entries] == ["pull up", "dumbbell bicep curl"]
    assert parsed.cardio == [
        {"activity": "walking", "distance": "3 miles", "duration": "", "notes": ""}
    ]
    assert parsed.bodyweight == "130 lbs" and not parsed.is_empty


def test_parsed_from_output_tolerates_missing_or_odd_kinds():
    # Only cardio: no "exercises" key at all is fine.
    parsed = parsed_from_output({"cardio": [{"activity": "run", "distance": "5k"}]})
    assert (
        parsed.entries == [] and parsed.cardio[0]["activity"] == "run" and parsed.bodyweight == ""
    )
    # Only a weigh-in, as a number.
    parsed = parsed_from_output({"exercises": [], "cardio": [], "bodyweight": 130})
    assert parsed.bodyweight == "130" and parsed.cardio == []
    # Nameless cardio rows are dropped; non-list cardio is ignored.
    parsed = parsed_from_output(
        {"exercises": [], "cardio": [{"distance": "3 mi"}], "bodyweight": None}
    )
    assert parsed.is_empty
    assert parsed_from_output({"exercises": [], "cardio": "walk"}).cardio == []
    with pytest.raises(BadOutputError):
        parsed_from_output({"nope": 1})
