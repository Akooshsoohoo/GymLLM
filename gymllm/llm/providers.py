"""LLM provider registry and the per-browser LLM configuration.

Every provider except Anthropic is reached through the OpenAI-compatible
chat-completions API, so adding one is a registry entry with a base URL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from flask import session

SESSION_KEY = "llm"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: Literal["openai", "anthropic"]
    base_url: str | None
    default_model: str
    needs_key: bool
    key_hint: str = ""
    is_local: bool = False
    model_suggestions: tuple[str, ...] = ()
    help_url: str = ""
    help_text: str = ""


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider(
            id="openai",
            label="OpenAI",
            kind="openai",
            base_url=None,
            default_model="gpt-4o-mini",
            needs_key=True,
            key_hint="sk-...",
            model_suggestions=("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o", "gpt-4.1"),
            help_url="https://platform.openai.com/api-keys",
            help_text="Create a key at platform.openai.com/api-keys.",
        ),
        Provider(
            id="anthropic",
            label="Anthropic (Claude)",
            kind="anthropic",
            base_url=None,
            default_model="claude-opus-5",
            needs_key=True,
            key_hint="sk-ant-...",
            model_suggestions=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"),
            help_url="https://console.anthropic.com/settings/keys",
            help_text="Create a key at console.anthropic.com.",
        ),
        Provider(
            id="ollama",
            label="Ollama (local)",
            kind="openai",
            base_url="http://localhost:11434/v1",
            default_model="llama3.2",
            needs_key=False,
            is_local=True,
            model_suggestions=("llama3.2", "llama3.1", "mistral", "qwen2.5", "phi3"),
            help_url="https://ollama.com",
            help_text="Install Ollama, run `ollama pull llama3.2`, and keep Ollama running.",
        ),
        Provider(
            id="lmstudio",
            label="LM Studio (local)",
            kind="openai",
            base_url="http://localhost:1234/v1",
            default_model="local-model",
            needs_key=False,
            is_local=True,
            help_url="https://lmstudio.ai",
            help_text="Start the LM Studio local server and load a model.",
        ),
        Provider(
            id="groq",
            label="Groq",
            kind="openai",
            base_url="https://api.groq.com/openai/v1",
            default_model="llama-3.3-70b-versatile",
            needs_key=True,
            key_hint="gsk_...",
            model_suggestions=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
            help_url="https://console.groq.com/keys",
        ),
        Provider(
            id="openrouter",
            label="OpenRouter",
            kind="openai",
            base_url="https://openrouter.ai/api/v1",
            default_model="openai/gpt-4o-mini",
            needs_key=True,
            key_hint="sk-or-...",
            model_suggestions=(
                "openai/gpt-4o-mini",
                "anthropic/claude-sonnet-5",
                "meta-llama/llama-3.3-70b-instruct",
            ),
            help_url="https://openrouter.ai/keys",
        ),
        Provider(
            id="gemini",
            label="Google Gemini",
            kind="openai",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model="gemini-2.0-flash",
            needs_key=True,
            model_suggestions=("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"),
            help_url="https://aistudio.google.com/apikey",
        ),
        Provider(
            id="custom",
            label="Custom (OpenAI-compatible)",
            kind="openai",
            base_url=None,
            default_model="",
            needs_key=False,
            help_text=(
                "Any server that speaks the OpenAI chat-completions API: "
                "vLLM, LiteLLM, a tunnelled Ollama, ..."
            ),
        ),
    )
}


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""

    @property
    def provider_info(self) -> Provider:
        return PROVIDERS[self.provider]

    @property
    def effective_base_url(self) -> str | None:
        if self.provider == "custom":
            return self.base_url.strip().rstrip("/") or None
        return self.provider_info.base_url

    @property
    def is_local(self) -> bool:
        return self.provider_info.is_local

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.provider not in PROVIDERS:
            return ["Unknown provider."]
        info = self.provider_info
        if not self.model.strip():
            errors.append("Model name is required.")
        if info.needs_key and not self.api_key.strip():
            errors.append(f"{info.label} needs an API key.")
        if self.provider == "custom":
            url = self.base_url.strip()
            if not url.startswith(("http://", "https://")):
                errors.append("Custom base URL must start with http:// or https://.")
        return errors

    def to_session(self) -> None:
        session[SESSION_KEY] = asdict(self)
        session.permanent = True

    @classmethod
    def from_session(cls) -> LLMConfig | None:
        return cls.from_dict(session.get(SESSION_KEY))

    @classmethod
    def from_dict(cls, data) -> LLMConfig | None:
        if not isinstance(data, dict):
            return None
        provider = str(data.get("provider", ""))
        if provider not in PROVIDERS:
            return None
        return cls(
            provider=provider,
            model=str(data.get("model", "") or ""),
            api_key=str(data.get("api_key", "") or ""),
            base_url=str(data.get("base_url", "") or ""),
        )

    def describe(self) -> str:
        return f"{self.provider_info.label} · {self.model}"
