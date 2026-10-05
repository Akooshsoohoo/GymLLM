import pytest

from gymllm.exercises import (
    ACTIVITY_NAMES,
    EXERCISE_NAMES,
    EXERCISES,
    MOVEMENT_NAMES,
    llm_tags,
    match_exercise,
)
from gymllm.llm.client import LLMError
from tests.conftest import FakeLLM


def test_list_loaded_from_package_data():
    assert "barbell bench press" in EXERCISE_NAMES
    assert len(EXERCISE_NAMES) > 100


def test_empty_name_does_not_match_anything():
    assert match_exercise("") is None
    assert match_exercise("   ") is None
    assert match_exercise(None) is None


def test_exact_match_is_case_and_space_insensitive():
    name, tags = match_exercise("  Barbell   Bench Press ")
    assert name == "barbell bench press"
    assert "chest" in tags


def test_fuzzy_match_fixes_typos():
    name, _ = match_exercise("barbel bench pres")
    assert name == "barbell bench press"


def test_generic_name_picks_least_specific_variant():
    name, _ = match_exercise("bench press")
    assert name == "barbell bench press"


def test_raw_name_containing_canonical_picks_most_specific():
    name, _ = match_exercise("incline barbell bench press with pause")
    assert name == "incline barbell bench press"


def test_short_word_does_not_match_random_substring():
    result = match_exercise("row")
    # Either no match or a canonical name that actually contains the word "row".
    assert result is None or "row" in result[0].split()


def test_unknown_exercise_returns_none():
    assert match_exercise("underwater basket weaving") is None


def test_every_listed_name_and_alias_matches_its_own_row():
    for name, tags, aliases in EXERCISES:
        assert match_exercise(name) == (name, tags)
        for alias in aliases:
            assert match_exercise(alias) == (name, tags), alias


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("barbell front squat", "front squat (barbell)"),  # word order and brackets
        ("one arm dumbbell row", "dumbbell one-arm row"),
        ("DB RDLs", "romanian deadlift (dumbbell)"),  # abbreviations and plurals
        ("pullups", "bodyweight pull-up"),
        ("skull crushers", "skullcrushers (ez bar)"),
        ("hex bar deadlift", "trap bar deadlift"),
        ("cable flyes", "cable chest fly"),
        ("squat", "barbell back squat"),  # a nickname for the usual version
        ("ohp", "barbell overhead press"),
        ("leg press", "leg press machine"),
        ("bench press touch and go", "barbell bench press"),  # how it was done
    ],
)
def test_other_ways_of_writing_a_listed_exercise(raw, expected):
    assert match_exercise(raw)[0] == expected


def test_another_movement_is_never_folded_into_a_shorter_name():
    assert match_exercise("romanian deadlift")[0] == "romanian deadlift (barbell)"
    assert match_exercise("walking lunges")[0] == "walking lunges (dumbbell)"
    assert match_exercise("sots press") is None


def test_unlisted_setup_keeps_its_own_name_with_the_listed_tags():
    name, tags = match_exercise("seated cable lateral raise")
    assert name == "seated cable lateral raise"
    assert tags == match_exercise("cable lateral raise")[1]
    assert match_exercise("cable lateral raise seated")[0] == name  # one name per exercise
    assert match_exercise(name) == (name, tags)


def test_unlisted_equipment_keeps_its_own_name_with_the_listed_tags():
    name, tags = match_exercise("trap bar romanian deadlift")
    assert name == "trap bar romanian deadlift"
    assert tags == match_exercise("romanian deadlift")[1]
    assert match_exercise(name) == (name, tags)


def test_one_sided_version_is_tagged_unilateral():
    name, tags = match_exercise("single arm machine lateral raise")
    assert name == "single arm machine lateral raise"
    assert tags.split(";")[-1] == "unilateral"


def test_prompt_lists_each_movement_once():
    assert "bench press" in MOVEMENT_NAMES
    assert not any("dumbbell bench" in m for m in MOVEMENT_NAMES)
    assert len(MOVEMENT_NAMES) == len(set(MOVEMENT_NAMES)) < len(EXERCISE_NAMES)


def test_activities_loaded():
    assert "Running" in ACTIVITY_NAMES and "Pickleball" in ACTIVITY_NAMES


def test_llm_tags_cleans_list_and_string_forms():
    assert llm_tags("x", FakeLLM().queue({"tags": [" Back ", "pull", "back", ""]})) == "back;pull"
    assert (
        llm_tags("x", FakeLLM().queue({"tags": "chest; push ,compound"})) == "chest;push;compound"
    )


def test_llm_tags_swallows_errors_and_bad_shapes():
    llm = FakeLLM()
    llm.error = LLMError("boom")
    assert llm_tags("x", llm) == ""
    assert llm_tags("x", FakeLLM().queue({"nope": 1})) == ""
    assert llm_tags("x", FakeLLM().queue(["a", "b"])) == ""


def test_clean_tags():
    from gymllm.exercises import clean_tags

    assert clean_tags(["Back", " pull", "back", ""]) == "back;pull"
    assert clean_tags("Chest, push; Chest") == "chest;push"
    assert clean_tags(None) == "" and clean_tags(42) == ""
