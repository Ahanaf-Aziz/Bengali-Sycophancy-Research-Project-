"""Check API keys and find exact model names.

Run from the repository root:

    uv run python -m bengali_sycophancy.list_models --filter gpt
    uv run python -m bengali_sycophancy.list_models --test claude gpt judge

Listing is free. ``--test`` sends "Reply with the single word OK." once to each
named model (``judge`` means the judge in config.yaml) and costs a few tokens.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from bengali_sycophancy.config import ModelConfig, load_config
from bengali_sycophancy.constants import KEY_ENV_NAMES, OPENROUTER_BASE_URL, Provider
from bengali_sycophancy.providers import call_model, check_credentials

TEST_PROMPT = "Reply with the single word OK."


def list_model_ids(provider: Provider) -> list[str]:
    key = os.environ[KEY_ENV_NAMES[provider]]
    if provider is Provider.ANTHROPIC:
        import anthropic

        return [m.id for m in anthropic.Anthropic(api_key=key).models.list(limit=100)]
    if provider is Provider.OPENAI:
        from openai import OpenAI

        return [m.id for m in OpenAI(api_key=key).models.list()]
    if provider is Provider.OPENROUTER:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=OPENROUTER_BASE_URL)
        return [m.id for m in client.models.list()]
    if provider is Provider.COHERE:
        import cohere

        return [m.name for m in cohere.ClientV2(api_key=key).models.list().models]
    return []


def print_lists(name_filter: str) -> None:
    for provider, env_name in KEY_ENV_NAMES.items():
        if not os.environ.get(env_name):
            print(f"\n[{provider.value}] no {env_name} in .env, skipped")
            continue
        try:
            ids = sorted(
                i for i in list_model_ids(provider) if name_filter.lower() in i.lower()
            )
        except Exception as e:  # noqa: BLE001 - report and go on to the next provider
            print(
                f"\n[{provider.value}] could not list models: {type(e).__name__}: {e}"
            )
            continue
        suffix = f" containing '{name_filter}'" if name_filter else ""
        print(f"\n[{provider.value}] {len(ids)} models{suffix}")
        for model_id in ids:
            print(f"   {model_id}")


def run_test_calls(targets: list[ModelConfig]) -> int:
    failures = 0
    for model in targets:
        if model.is_placeholder:
            print(f"{model.name:10s} skipped: model id is still a placeholder")
            failures += 1
            continue
        check_credentials(model)
        result = call_model(model, [{"role": "user", "content": TEST_PROMPT}])
        if result.ok:
            print(
                f"{model.name:10s} {model.model_id:36s} -> {result.text[:40]!r} "
                f"(temperature sent: {result.temperature_used})"
            )
        else:
            print(f"{model.name:10s} {model.model_id:36s} FAILED: {result.error}")
            failures += 1
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check keys and model names.")
    parser.add_argument("--filter", default="", help="only names containing this text")
    parser.add_argument("--test", nargs="+", default=None, metavar="NAME")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.test is None:
        print_lists(args.filter)
        return 0
    config = load_config(args.config)
    targets = [config.judge if n == "judge" else config.get_model(n) for n in args.test]
    return 1 if run_test_calls(targets) else 0


if __name__ == "__main__":
    raise SystemExit(main())
