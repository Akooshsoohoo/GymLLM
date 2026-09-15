"""LLM provider registry and the per-browser LLM configuration.

Every provider except Anthropic is reached through the OpenAI-compatible
chat-completions API, so adding one is a registry entry with a base URL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from flask import current_app, session

SESSION_KEY = "llm"
SITE_PROVIDER = "site"


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
        # Virtual provider: the owner's shared key, configured with SITE_LLM_* env
        # vars and resolved server-side (see LLMConfig.resolved). Listed first so
        # it is the default choice wherever it is available.
        Provider(
            id=SITE_PROVIDER,
            label="GymLLM shared model",
            kind="openai",
            base_url=None,
            default_model="",
            needs_key=False,
            help_text=(
                "Free and shared by everyone on this site, with a daily cap per person. "
                "Bring your own key or a local model for unlimited use."
            ),
        ),
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

    @property
    def is_site(self) -> bool:
        return self.provider == SITE_PROVIDER

    @staticmethod
    def site_settings() -> dict | None:
        """The SITE_LLM app config, or None when the shared model is not set up."""
        return current_app.config.get("SITE_LLM")

    @classmethod
    def site_default(cls) -> LLMConfig | None:
        """A config for the shared model if it is available on this server."""
        return cls(provider=SITE_PROVIDER, model="") if cls.site_settings() else None

    def resolved(self) -> LLMConfig:
        """The config to actually call: the shared model maps to the owner's real one."""
        if not self.is_site:
            return self
        site = self.site_settings() or {}
        return LLMConfig(
            provider=site.get("provider", ""),
            model=site.get("model", ""),
            api_key=site.get("api_key", ""),
            base_url=site.get("base_url", ""),
        )

    @property
    def runs_in_browser(self) -> bool:
        """Local providers are called from the user's browser, never from the server,
        so a hosted copy of GymLLM can still reach the model on the visitor's machine."""
        return self.provider_info.is_local

    def browser_config(self) -> dict | None:
        """What page JavaScript needs to call the model directly, or None."""
        if not self.runs_in_browser:
            return None
        return {
            "base_url": self.effective_base_url,
            "model": self.model,
            "label": self.provider_info.label,
        }

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.provider not in PROVIDERS:
            return ["Unknown provider."]
        if self.is_site:
            return (
                [] if self.site_settings() else ["The shared model is not set up on this server."]
            )
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
        data = asdict(self)
        if self.is_site:  # never let a key or model name for the shared provider leak in
            data.update(model="", api_key="", base_url="")
        session[SESSION_KEY] = data
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
        if self.is_site:
            return f"{self.provider_info.label} · {self.resolved().model}"
        return f"{self.provider_info.label} · {self.model}"
