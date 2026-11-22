"""Closed vocabularies and fixed settings shared across the package.

Values that flow through result files are ``str`` enums, so they stay
JSON-serialisable and compare equal to the plain strings stored on disk.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class Task(str, Enum):
    SUGGESTED_ANSWER = "suggested_answer"
    ARE_YOU_SURE = "are_you_sure"


class Condition(str, Enum):
    """Prompt conditions with fixed names.

    Set 4 conditions are not listed here: they take the pushback line ids from
    ``dataset/set4_pushback.csv`` (``P1`` to ``P6``), so the data file stays
    the single source of truth for them.
    """

    PLAIN = "plain"
    WRONG_GUESS = "wrong_guess"
    TURN1 = "turn1"
    STANDARD = "standard"


class Reply(str, Enum):
    """Which reply in a record is scored."""

    ANSWER = "answer"
    FIRST = "first"
    FINAL = "final"


class Label(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNCLEAR = "unclear"
    NEEDS_JUDGE = "needs_judge"
    JUDGE_ERROR = "judge_error"


class Method(str, Enum):
    RULE = "rule"
    JUDGE = "judge"
    NONE = "none"


class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    COHERE = "cohere"
    MOCK = "mock"


class CallStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


# Labels that count in the analysis. Everything else is reported, then left out.
CLEAR_LABELS = frozenset({Label.CORRECT.value, Label.INCORRECT.value})

# Labels that score.py retries when a judge is available.
RETRY_LABELS = frozenset({Label.NEEDS_JUDGE.value, Label.JUDGE_ERROR.value})

# API key environment variable per provider. Keys are read from .env only.
KEY_ENV_NAMES = {
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.OPENROUTER: "OPENROUTER_API_KEY",
    Provider.COHERE: "COHERE_API_KEY",
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# A model id containing this text has not been chosen yet.
PLACEHOLDER_MODEL_ID = "CHANGE-ME"

# Waits between retries of one API call. Errors that cannot succeed on a retry
# (bad request, bad key, unknown model) are not retried.
RETRY_WAITS_S = (2, 4, 8, 16)
NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 422})

# A run stops after this many failed calls in a row, so a wrong setting does
# not fail thousands of calls one by one.
MAX_CONSECUTIVE_ERRORS = 5

# Statistics. Fixed seeds so every table can be reproduced exactly.
RNG_SEED = 0
BOOTSTRAP_RESAMPLES = 2000
JUDGE_SAMPLE_SEED = 7

# Scoring rules.
TRUTHFULQA_ID_PREFIX = "tf"
SHORT_ANSWER_MAX_CHARS = 3
BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
BENGALI_BLOCK = ("ঀ", "৿")

# Where results go. Real runs go to outputs/ (published); the mock model always
# writes to scratch/ (Git-ignored), so fake results can never be published.
DEFAULT_OUTPUTS = Path("outputs")
MOCK_OUTPUTS = Path("scratch")
