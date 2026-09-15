"""Thin, provider-agnostic wrapper: one `complete_json(system, user)` call.

Errors from either SDK are mapped onto the small LLMError hierarchy so the
routes can show a friendly message without knowing which SDK was used.
"""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic
import openai

from .providers import LLMConfig

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMError(Exception):
    """Base error carrying a message safe to show to the user."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AuthError(LLMError):
    pass


class RateLimitError(LLMError):
    pass


class LLMConnectionError(LLMError):
    pass


class BadOutputError(LLMError):
    pass


def extract_json(text: str | None) -> Any:
    """Parse JSON from model output, tolerating code fences and stray prose."""
    if text is None:
        raise BadOutputError("The model returned an empty response.")
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost object or array embedded in prose.
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not starts:
        raise BadOutputError("The model did not return JSON.")
    start = min(starts)
    closer = "}" if cleaned[start] == "{" else "]"
    end = cleaned.rfind(closer)
    if end <= start:
        raise BadOutputError("The model returned malformed JSON.")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as e:
        raise BadOutputError("The model returned malformed JSON.") from e


def _connection_message(config: LLMConfig) -> str:
    label = config.provider_info.label
    if config.is_local or config.provider == "custom":
        return (
            f"Could not reach {label} at {config.effective_base_url}. Make sure the server "
            "is running and reachable from where GymLLM is hosted."
        )
    return f"Could not connect to {label}. Check your network and the base URL, then try again."


class OpenAICompatClient:
    """Any server speaking the OpenAI chat-completions API."""

    def __init__(self, config: LLMConfig, timeout: float = 60.0):
        self.config = config
        self._client = openai.OpenAI(
            api_key=config.api_key.strip() or "not-needed",
            base_url=config.effective_base_url,
            timeout=timeout,
            max_retries=1,
        )

    def _create(self, messages, **extra):
        return self._client.chat.completions.create(
            model=self.config.model, messages=messages, **extra
        )

    def complete_json(self, system: str, user: str) -> Any:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        label = self.config.provider_info.label
        try:
            try:
                resp = self._create(
                    messages, temperature=0, response_format={"type": "json_object"}
                )
            except openai.BadRequestError:
                # Older/other servers reject response_format or temperature.
                resp = self._create(messages)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            raise AuthError(f"{label} rejected the API key. Check it on the Settings page.") from e
        except openai.RateLimitError as e:
            raise RateLimitError(
                f"{label} is rate-limiting you or you are out of credits. Try again shortly."
            ) from e
        except openai.NotFoundError as e:
            raise LLMError(
                f"Model '{self.config.model}' was not found on {label}. "
                "Check the model name on the Settings page."
            ) from e
        except openai.APIConnectionError as e:  # includes timeouts
            raise LLMConnectionError(_connection_message(self.config)) from e
        except openai.APIStatusError as e:
            raise LLMError(f"{label} returned an error ({e.status_code}): {e.message}") from e
        except openai.OpenAIError as e:
            raise LLMError(f"{label} error: {e}") from e

        if not resp.choices:
            raise BadOutputError("The model returned no choices.")
        return extract_json(resp.choices[0].message.content or "")

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self._client.models.list())


class AnthropicClient:
    def __init__(self, config: LLMConfig, timeout: float = 60.0):
        self.config = config
        self._client = anthropic.Anthropic(
            api_key=config.api_key.strip(), timeout=timeout, max_retries=1
        )

    def complete_json(self, system: str, user: str) -> Any:
        label = self.config.provider_info.label
        try:
            resp = self._client.messages.create(
                model=self.config.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise AuthError(f"{label} rejected the API key. Check it on the Settings page.") from e
        except anthropic.RateLimitError as e:
            raise RateLimitError(
                f"{label} is rate-limiting you or you are out of credits. Try again shortly."
            ) from e
        except anthropic.NotFoundError as e:
            raise LLMError(
                f"Model '{self.config.model}' was not found on {label}. "
                "Check the model name on the Settings page."
            ) from e
        except anthropic.APIConnectionError as e:
            raise LLMConnectionError(_connection_message(self.config)) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"{label} returned an error ({e.status_code}): {e.message}") from e
        except anthropic.AnthropicError as e:
            raise LLMError(f"{label} error: {e}") from e

        if resp.stop_reason == "refusal":
            raise LLMError("The model declined to process this input.")
        text = "".join(block.text for block in resp.content if block.type == "text")
        return extract_json(text)


def get_client(config: LLMConfig):
    if config.provider_info.kind == "anthropic":
        return AnthropicClient(config)
    return OpenAICompatClient(config)


def test_connection(config: LLMConfig, client=None) -> tuple[bool, str]:
    """Make one tiny call and report a human-readable result."""
    client = client or get_client(config)
    try:
        data = client.complete_json(
            "You are a connectivity check. Reply with JSON only.",
            'Return exactly this JSON object: {"ok": true}',
        )
    except LLMError as e:
        return False, e.user_message
    if not isinstance(data, dict):
        return False, "The model answered, but not with a JSON object. Try a different model."
    msg = f"Connected to {config.describe()}."
    if config.is_local and hasattr(client, "list_models"):
        try:
            models = client.list_models()
            if models:
                msg += " Installed models: " + ", ".join(models[:12])
                if len(models) > 12:
                    msg += ", ..."
        except Exception:  # noqa: BLE001 - listing is purely informational
            pass
    return True, msg
