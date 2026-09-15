from gymllm.exercises import EXERCISE_NAMES, llm_tags, match_exercise
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
