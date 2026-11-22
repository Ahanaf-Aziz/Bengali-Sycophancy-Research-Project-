"""Exceptions raised by the package."""

from __future__ import annotations


class BenSycError(Exception):
    """Base exception for the Bengali SycophancyEval package."""


class ConfigError(BenSycError):
    """Raised when config.yaml is missing a field or names something unknown."""


class MissingKeyError(BenSycError):
    """Raised when a provider's API key is not set in .env."""


class DatasetError(BenSycError):
    """Raised when a dataset file is missing columns or has broken rows."""


class OutputsError(BenSycError):
    """Raised when results would be written to, or read from, the wrong place."""
