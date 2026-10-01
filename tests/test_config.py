import pytest

from gymllm.config import ConfigError, admin_emails, build_config, is_local_sqlite, site_llm_config

BASE = {"FLASK_SECRET_KEY": "s"}


def test_admin_emails_parses_and_lowercases_comma_separated_list():
    assert admin_emails({"ADMIN_EMAILS": "Me@Example.com, other@example.com"}) == {
        "me@example.com",
        "other@example.com",
    }
    assert admin_emails({}) == set()


def test_is_local_sqlite():
    assert is_local_sqlite("sqlite:///gymllm.db") is True
    assert is_local_sqlite("sqlite://") is True
    assert is_local_sqlite("postgresql://user:pass@host/db") is False


def test_no_site_key_means_no_shared_model():
    assert site_llm_config({}) is None
    assert build_config(BASE)["SITE_LLM"] is None


def test_site_defaults_to_groq():
    cfg = build_config({**BASE, "SITE_LLM_API_KEY": "gsk-1"})["SITE_LLM"]
    assert cfg == {
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
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
