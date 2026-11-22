"""Load config.yaml into frozen dataclasses.

All coercion of the YAML values happens in the ``from_dict`` classmethods, so
the rest of the code can trust the types. Dataset paths in the YAML are relative
to the folder that holds config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bengali_sycophancy.constants import PLACEHOLDER_MODEL_ID, Provider
from bengali_sycophancy.errors import ConfigError


@dataclass(frozen=True)
class ModelConfig:
    """Settings for one model, tested or judge.

    Attributes:
        name: Short name used on the command line and in folder names.
        provider: Which API the model is reached through.
        model_id: Exact model name the provider expects.
        temperature: Requested sampling temperature, or None to send none.
        max_tokens: Output token limit per call, thinking included.
        extra: Provider-specific request fields, such as a reasoning setting.
    """

    name: str
    provider: Provider
    model_id: str
    temperature: float | None = None
    max_tokens: int = 400
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> ModelConfig:
        try:
            provider = Provider(d["provider"])
        except (KeyError, ValueError) as e:
            raise ConfigError(
                f"Model '{name}': unknown or missing provider ({e})."
            ) from e
        if not d.get("model"):
            raise ConfigError(f"Model '{name}': 'model' is missing.")
        temperature = d.get("temperature")
        return cls(
            name=name,
            provider=provider,
            model_id=str(d["model"]),
            temperature=None if temperature is None else float(temperature),
            max_tokens=int(d.get("max_tokens", 400)),
            extra=dict(d.get("extra") or {}),
        )

    @property
    def is_placeholder(self) -> bool:
        return PLACEHOLDER_MODEL_ID in self.model_id

    def describe(self) -> dict[str, Any]:
        """The settings that go into run logs. Never contains a key."""
        return {
            "name": self.name,
            "provider": self.provider.value,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class SetSpec:
    """One cell of the 2x2 grid.

    Attributes:
        name: Set name, such as ``set1``.
        path: CSV file with the questions.
        content: Whose culture the questions are about.
        language: Language the questions are asked in.
    """

    name: str
    path: Path
    content: str
    language: str


@dataclass(frozen=True)
class Set4Spec:
    """The extra pushback test on one set.

    Attributes:
        enabled: Whether to run the six Set 4 pushback lines.
        path: CSV file with the pushback lines.
        applies_to: The set the lines are used on.
    """

    enabled: bool
    path: Path
    applies_to: str


@dataclass(frozen=True)
class ProjectConfig:
    """Everything in config.yaml.

    Attributes:
        models: Tested models by name.
        judge: The grading model.
        sets: The four grid cells by name, in run order.
        set4: The extra pushback test.
    """

    models: dict[str, ModelConfig]
    judge: ModelConfig
    sets: dict[str, SetSpec]
    set4: Set4Spec

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, root: Path) -> ProjectConfig:
        for section in ("models", "judge", "sets", "set4"):
            if section not in d:
                raise ConfigError(f"config.yaml has no '{section}' section.")
        models = {n: ModelConfig.from_dict(n, m) for n, m in d["models"].items()}
        sets = {
            n: SetSpec(
                name=n,
                path=root / s["file"],
                content=str(s["content"]),
                language=str(s["language"]),
            )
            for n, s in d["sets"].items()
        }
        s4 = d["set4"]
        set4 = Set4Spec(
            enabled=bool(s4.get("enabled", False)),
            path=root / s4["file"],
            applies_to=str(s4["applies_to"]),
        )
        if set4.applies_to not in sets:
            raise ConfigError(f"set4.applies_to '{set4.applies_to}' is not a set.")
        return cls(
            models=models,
            judge=ModelConfig.from_dict("judge", d["judge"]),
            sets=sets,
            set4=set4,
        )

    def get_model(self, name: str) -> ModelConfig:
        if name not in self.models:
            choices = ", ".join(self.models)
            raise ConfigError(f"'{name}' is not in config.yaml. Choose from: {choices}")
        return self.models[name]


def load_config(path: Path) -> ProjectConfig:
    if not path.exists():
        raise ConfigError(f"{path} not found. Run commands from the repository root.")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ProjectConfig.from_dict(raw, root=path.resolve().parent)
