import openai
import pytest

from gymllm.llm import client as llm_client
from gymllm.llm.client import (
    AnthropicClient,
    AuthError,
    LLMConnectionError,
    OpenAICompatClient,
    RateLimitError,
    get_client,
)
from gymllm.llm.client import (
    test_connection as check_connection,
)
from gymllm.llm.providers import PROVIDERS, LLMConfig
from tests.conftest import FakeLLM


def test_every_provider_has_a_usable_default():
    for p in PROVIDERS.values():
        assert p.kind in ("openai", "anthropic")
        if p.id != "custom":
            assert p.default_model
        if p.kind == "openai" and p.id not in ("openai", "custom"):
            assert p.base_url.startswith("http")


def test_validate_requires_key_for_hosted_providers():
    assert "API key" in LLMConfig("openai", "gpt-4o-mini").validate()[0]
    assert LLMConfig("ollama", "llama3.2").validate() == []
    assert "Model" in LLMConfig("ollama", "").validate()[0]
    assert LLMConfig("custom", "m", base_url="ftp://x").validate()
    assert LLMConfig("custom", "m", base_url="http://localhost:8000/v1").validate() == []
    assert LLMConfig("nope", "m").validate() == ["Unknown provider."]


def test_effective_base_url():
    assert LLMConfig("openai", "m").effective_base_url is None
    assert LLMConfig("ollama", "m").effective_base_url == "http://localhost:11434/v1"
    assert LLMConfig("custom", "m", base_url="http://h/v1/ ").effective_base_url == "http://h/v1"


def test_from_dict_rejects_garbage():
    assert LLMConfig.from_dict(None) is None
    assert LLMConfig.from_dict({"provider": "bogus"}) is None
    cfg = LLMConfig.from_dict({"provider": "groq", "model": None})
    assert cfg.provider == "groq" and cfg.model == ""


def test_get_client_picks_sdk_by_kind():
    assert isinstance(
        get_client(LLMConfig("anthropic", "claude-opus-5", api_key="k")), AnthropicClient
    )
    assert isinstance(get_client(LLMConfig("ollama", "llama3.2")), OpenAICompatClient)


class _Resp:
    def __init__(self, content):
        msg = type("Msg", (), {"content": content})()
        self.choices = [type("Choice", (), {"message": msg})()]


def _openai_client_with(create_impl):
    cfg = LLMConfig("openai", "gpt-4o-mini", api_key="sk-x")
    c = OpenAICompatClient(cfg)
    c._create = create_impl
    return c


def test_openai_compat_falls_back_without_response_format():
    calls = []

    def create(messages, **extra):
        calls.append(extra)
        if "response_format" in extra:
            raise openai.BadRequestError("nope", response=_fake_response(400), body=None)
        return _Resp('{"ok": true}')

    c = _openai_client_with(create)
    assert c.complete_json("s", "u") == {"ok": True}
    assert "response_format" in calls[0] and calls[1] == {}


def _fake_response(status):
    import httpx

    req = httpx.Request("POST", "http://x")
    return httpx.Response(status, request=req)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (
            lambda: openai.AuthenticationError("bad", response=_fake_response(401), body=None),
            AuthError,
        ),
        (
            lambda: openai.RateLimitError("slow", response=_fake_response(429), body=None),
            RateLimitError,
        ),
        (lambda: openai.APIConnectionError(request=_fake_response(0).request), LLMConnectionError),
    ],
)
def test_openai_errors_are_mapped(exc, expected):
    def create(messages, **extra):
        raise exc()

    with pytest.raises(expected):
        _openai_client_with(create).complete_json("s", "u")


def test_custom_connection_error_names_the_url():
    def create(messages, **extra):
        raise openai.APIConnectionError(request=_fake_response(0).request)

    c = OpenAICompatClient(LLMConfig("custom", "m", base_url="http://models.example.com/v1"))
    c._create = create
    with pytest.raises(LLMConnectionError) as info:
        c.complete_json("s", "u")
    assert "http://models.example.com/v1" in info.value.user_message
    assert "reachable from where GymLLM is hosted" in info.value.user_message


def test_test_connection_reports_success_and_local_models():
    cfg = LLMConfig("ollama", "llama3.2")
    ok, msg = check_connection(cfg, client=FakeLLM().queue({"ok": True}))
    assert ok and "llama3.2" in msg and "mistral" in msg


def test_test_connection_reports_failure_message():
    fake = FakeLLM()
    fake.error = AuthError("bad key")
    ok, msg = check_connection(LLMConfig("openai", "m", api_key="k"), client=fake)
    assert not ok and msg == "bad key"
    ok, msg = check_connection(LLMConfig("openai", "m", api_key="k"), client=FakeLLM().queue([1]))
    assert not ok and "JSON object" in msg


def test_module_exports_error_hierarchy():
    assert issubclass(llm_client.BadOutputError, llm_client.LLMError)


@pytest.mark.parametrize(
    "provider,expected",
    [("ollama", True), ("lmstudio", True), ("openai", False), ("custom", False)],
)
def test_runs_in_browser(provider, expected):
    cfg = LLMConfig(provider=provider, model="m", base_url="http://x.example/v1")
    assert cfg.runs_in_browser is expected
    if expected:
        assert cfg.browser_config() == {
            "base_url": cfg.effective_base_url,
            "model": "m",
            "label": cfg.provider_info.label,
        }
    else:
        assert cfg.browser_config() is None
