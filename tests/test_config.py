import pytest

from gymllm.config import ConfigError, build_config, site_llm_config

BASE = {"FLASK_SECRET_KEY": "s"}


def test_no_site_key_means_no_shared_model():
    assert site_llm_config({}) is None
    assert build_config(BASE)["SITE_LLM"] is None


def test_site_defaults_to_groq():
    cfg = build_config({**BASE, "SITE_LLM_API_KEY": "gsk-1"})["SITE_LLM"]
    assert cfg == {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "api_key": "gsk-1",
        "base_url": "",
        "daily_limit": 20,
    }


def test_site_overrides():
    cfg = site_llm_config(
        {
            "SITE_LLM_API_KEY": "k",
            "SITE_LLM_PROVIDER": "custom",
            "SITE_LLM_MODEL": "m",
            "SITE_LLM_BASE_URL": "https://h/v1",
            "SITE_LLM_DAILY_LIMIT": "5",
        }
    )
    assert cfg["provider"] == "custom" and cfg["base_url"] == "https://h/v1"
    assert cfg["model"] == "m" and cfg["daily_limit"] == 5


@pytest.mark.parametrize(
    "extra,match",
    [
        ({"SITE_LLM_PROVIDER": "nope"}, "hosted provider"),
        ({"SITE_LLM_PROVIDER": "ollama"}, "hosted provider"),
        ({"SITE_LLM_PROVIDER": "site"}, "hosted provider"),
        ({"SITE_LLM_PROVIDER": "custom"}, "SITE_LLM_BASE_URL"),
        ({"SITE_LLM_DAILY_LIMIT": "lots"}, "whole number"),
        ({"SITE_LLM_DAILY_LIMIT": "0"}, "at least 1"),
    ],
)
def test_site_config_errors(extra, match):
    with pytest.raises(ConfigError, match=match):
        site_llm_config({"SITE_LLM_API_KEY": "k", **extra})
