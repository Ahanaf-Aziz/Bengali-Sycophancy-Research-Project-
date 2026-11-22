"""Send a conversation to a model and return the reply as a result object.

API keys come from the ``.env`` file in the repository root and nowhere else.

Failure policy
--------------
A full run makes thousands of calls, so one failed call must not stop it.
``call_model`` never raises for an API problem: it returns a ``ChatResult``
whose ``status`` is ``error``, and the caller records it and moves on. Errors
that a retry cannot fix (a bad request, a wrong key, an unknown model) come back
at once; other errors are retried after 2, 4, 8 and 16 seconds. A missing key or
an unknown provider is a setup mistake, not an API problem, so
``check_credentials`` raises before any call is made.

Temperature
-----------
Claude Sonnet 5.5 returns a 400 error for ``temperature``, ``top_p`` and
``top_k``, and the Anthropic Python SDK 2.x has removed those fields, so no
temperature is ever sent to Anthropic. For other providers the configured
temperature is sent; if the error message names temperature, the call is made
once more without it. ``temperature_used`` records what was really sent, so
every result file says how each reply was produced.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from bengali_sycophancy.config import ModelConfig
from bengali_sycophancy.constants import (
    KEY_ENV_NAMES,
    NON_RETRYABLE_STATUS,
    OPENROUTER_BASE_URL,
    RETRY_WAITS_S,
    CallStatus,
    Provider,
)
from bengali_sycophancy.errors import ConfigError, MissingKeyError

load_dotenv()

Messages = list[dict[str, str]]


@dataclass(frozen=True)
class ChatResult:
    """The outcome of one model call.

    Attributes:
        status: ``ok`` or ``error``.
        text: The reply text, empty on error.
        input_tokens: Prompt tokens billed, when the provider reports them.
        output_tokens: Output tokens billed, thinking included.
        temperature_used: The temperature actually sent, or None.
        stop_reason: Why the model stopped, as the provider names it.
        error: Error type and message when ``status`` is ``error``.
    """

    status: CallStatus
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    temperature_used: float | None = None
    stop_reason: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is CallStatus.OK


def check_credentials(model: ModelConfig) -> None:
    """Raise unless the model's provider is known and its key is set."""
    if model.provider is Provider.MOCK:
        return
    env_name = KEY_ENV_NAMES.get(model.provider)
    if env_name is None:
        raise ConfigError(f"No key setting for provider '{model.provider.value}'.")
    if not os.environ.get(env_name):
        raise MissingKeyError(
            f"{env_name} is missing. Put it in .env (see .env.example)."
        )


def _status_code(error: Exception) -> int | None:
    code = getattr(error, "status_code", None)
    return code if isinstance(code, int) else None


def _with_retries(fn: Callable[[], Any]) -> Any:
    for wait_s in (*RETRY_WAITS_S, None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - every SDK has its own error types
            if wait_s is None or _status_code(e) in NON_RETRYABLE_STATUS:
                raise
            print(f"    API error ({type(e).__name__}). Retrying in {wait_s}s...")
            time.sleep(wait_s)
    raise AssertionError("unreachable")


def _with_temperature_fallback(
    make_call: Callable[[float | None], Any], temperature: float | None
) -> tuple[Any, float | None]:
    if temperature is None:
        return _with_retries(lambda: make_call(None)), None
    try:
        return _with_retries(lambda: make_call(temperature)), temperature
    except Exception as e:  # noqa: BLE001
        if "temperature" not in str(e).lower():
            raise
        print("    This model does not accept temperature; using its default.")
        return _with_retries(lambda: make_call(None)), None


def _call_anthropic(model: ModelConfig, messages: Messages) -> ChatResult:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ[KEY_ENV_NAMES[Provider.ANTHROPIC]])
    kwargs = {
        "model": model.model_id,
        "max_tokens": model.max_tokens,
        "messages": messages,
    }
    kwargs.update(model.extra)
    r = _with_retries(lambda: client.messages.create(**kwargs))
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return ChatResult(
        status=CallStatus.OK,
        text=text.strip(),
        input_tokens=r.usage.input_tokens,
        output_tokens=r.usage.output_tokens,
        temperature_used=None,
        stop_reason=r.stop_reason,
    )


def _call_openai_compatible(model: ModelConfig, messages: Messages) -> ChatResult:
    from openai import OpenAI

    if model.provider is Provider.OPENAI:
        client = OpenAI(api_key=os.environ[KEY_ENV_NAMES[Provider.OPENAI]])
        token_field = "max_completion_tokens"
    else:
        client = OpenAI(
            api_key=os.environ[KEY_ENV_NAMES[Provider.OPENROUTER]],
            base_url=OPENROUTER_BASE_URL,
        )
        token_field = "max_tokens"

    def make_call(temperature: float | None) -> Any:
        kwargs: dict[str, Any] = {
            "model": model.model_id,
            "messages": messages,
            token_field: model.max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        kwargs.update(model.extra)
        return client.chat.completions.create(**kwargs)

    r, temperature_used = _with_temperature_fallback(make_call, model.temperature)
    usage = getattr(r, "usage", None)
    return ChatResult(
        status=CallStatus.OK,
        text=(r.choices[0].message.content or "").strip(),
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
        temperature_used=temperature_used,
        stop_reason=r.choices[0].finish_reason,
    )


def _call_cohere(model: ModelConfig, messages: Messages) -> ChatResult:
    import cohere

    client = cohere.ClientV2(api_key=os.environ[KEY_ENV_NAMES[Provider.COHERE]])

    def make_call(temperature: float | None) -> Any:
        kwargs: dict[str, Any] = {
            "model": model.model_id,
            "messages": messages,
            "max_tokens": model.max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        kwargs.update(model.extra)
        return client.chat(**kwargs)

    r, temperature_used = _with_temperature_fallback(make_call, model.temperature)
    parts = r.message.content or []
    text = "".join(
        getattr(p, "text", "") or ""
        for p in parts
        if getattr(p, "type", "text") == "text"
    )
    tokens = getattr(getattr(r, "usage", None), "tokens", None)
    return ChatResult(
        status=CallStatus.OK,
        text=text.strip(),
        input_tokens=getattr(tokens, "input_tokens", None),
        output_tokens=getattr(tokens, "output_tokens", None),
        temperature_used=temperature_used,
        stop_reason=r.finish_reason,
    )


def _call_mock(
    model: ModelConfig, messages: Messages, answers: tuple[str, str] | None
) -> ChatResult:
    """A free stand-in model for testing the pipeline.

    It answers correctly at first, picks the user's wrong guess about 25% of the
    time when one is offered, and gives in to pushback about 30% of the time.
    The choice is a hash of the conversation, so reruns give the same replies.
    """
    correct, wrong = answers or ("?", "?")
    roll = int(hashlib.md5(str(messages).encode()).hexdigest(), 16) % 100
    n_user_turns = sum(1 for m in messages if m["role"] == "user")
    if n_user_turns == 1:
        content = messages[0]["content"]
        has_guess = "I think the answer is" in content or "আমার মনে হয় উত্তরটা" in content
        text = wrong if (has_guess and wrong in content and roll < 25) else correct
    else:
        text = wrong if roll < 30 else correct
    return ChatResult(
        status=CallStatus.OK,
        text=text,
        input_tokens=0,
        output_tokens=0,
        temperature_used=model.temperature,
        stop_reason="mock",
    )


def call_model(
    model: ModelConfig,
    messages: Messages,
    *,
    answers: tuple[str, str] | None = None,
) -> ChatResult:
    """Send ``messages`` to ``model``; never raises for an API problem.

    ``answers`` is the (correct, wrong) pair, used only by the mock model.
    """
    try:
        if model.provider is Provider.MOCK:
            return _call_mock(model, messages, answers)
        if model.provider is Provider.ANTHROPIC:
            return _call_anthropic(model, messages)
        if model.provider in (Provider.OPENAI, Provider.OPENROUTER):
            return _call_openai_compatible(model, messages)
        if model.provider is Provider.COHERE:
            return _call_cohere(model, messages)
    except Exception as e:  # noqa: BLE001 - recorded, see "Failure policy"
        return ChatResult(status=CallStatus.ERROR, error=f"{type(e).__name__}: {e}")
    raise ConfigError(f"Unknown provider: {model.provider}")
