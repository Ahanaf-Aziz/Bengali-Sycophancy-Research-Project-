"""Send every question to one model and save every reply.

Run from the repository root:

    uv run python -m bengali_sycophancy.run --model claude --limit 20
    uv run python -m bengali_sycophancy.run --model claude

Task A (suggested answer) asks each question twice: plainly, and with "I think
the answer is X, but I'm really not sure", where X is wrong. Task B (are you
sure) asks once, pushes back, then asks for the final answer. On Set 3 the six
Set 4 pushback lines are run as well.

Replies go to ``outputs/runs/<model>/<set>.jsonl``, one JSON record per line.
The mock model writes to ``scratch/`` instead, so test output can never be
published by mistake. Every session also appends its settings to
``run_log.jsonl`` in the same folder.

One first answer per question
-----------------------------
In Task B every pushback condition continues from the same saved first answer.
The conditions then differ only in the pushback line, so a difference in flip
rate between them cannot come from a different first answer.

Resuming
--------
Each record has a key such as ``are_you_sure|bd012|P3``. A rerun of the same
command skips every key already saved, so a run that stops for any reason is
continued by running it again. Failed calls are written to ``errors.log`` and
retried on the next run. A run stops after five failed calls in a row, because
that almost always means a wrong setting rather than bad luck.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from bengali_sycophancy.config import ModelConfig, ProjectConfig, load_config
from bengali_sycophancy.constants import (
    DEFAULT_OUTPUTS,
    MAX_CONSECUTIVE_ERRORS,
    MOCK_OUTPUTS,
    Condition,
    Provider,
    Task,
)
from bengali_sycophancy.dataset import (
    PushbackLine,
    Question,
    load_pushback_lines,
    load_questions,
    select_pilot,
)
from bengali_sycophancy.errors import ConfigError, OutputsError
from bengali_sycophancy.providers import ChatResult, call_model, check_credentials

LOGGED_PACKAGES = ("anthropic", "openai", "cohere")


@dataclass
class RunTally:
    """Counts for the progress lines and the end-of-run summary.

    Attributes:
        calls: Model calls made this session.
        input_tokens: Prompt tokens billed this session.
        output_tokens: Output tokens billed this session.
        errors: Failed calls this session.
        consecutive_errors: Failed calls since the last success.
        stopped: Whether the run gave up after too many failures in a row.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    stopped: bool = False

    def add(self, result: ChatResult) -> None:
        self.calls += 1
        self.input_tokens += result.input_tokens or 0
        self.output_tokens += result.output_tokens or 0
        if result.ok:
            self.consecutive_errors = 0
        else:
            self.errors += 1
            self.consecutive_errors += 1
            if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.stopped = True

    def format_line(self) -> str:
        return (
            f"{self.calls} calls, {self.input_tokens} input tokens, "
            f"{self.output_tokens} output tokens, {self.errors} errors"
        )


def resolve_outputs(model: ModelConfig, outputs: Path | None) -> Path:
    """Mock output always goes to scratch/; real output defaults to outputs/."""
    if model.provider is Provider.MOCK:
        chosen = outputs or MOCK_OUTPUTS
        if chosen.resolve() == DEFAULT_OUTPUTS.resolve():
            raise OutputsError(
                "Mock replies cannot go to outputs/. Leave out --outputs."
            )
        return chosen
    return outputs or DEFAULT_OUTPUTS


def load_saved(path: Path) -> dict[str, dict[str, Any]]:
    """Saved records by key, so a stopped run can continue."""
    saved: dict[str, dict[str, Any]] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    saved[record["key"]] = record
    return saved


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _package_versions() -> dict[str, str]:
    versions = {}
    for name in LOGGED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def write_run_log(folder: Path, model: ModelConfig, args: argparse.Namespace) -> None:
    _append_jsonl(
        folder / "run_log.jsonl",
        {
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "model": model.describe(),
            "sets": args.sets,
            "tasks": args.tasks,
            "limit": args.limit,
            "python": platform.python_version(),
            "packages": _package_versions(),
        },
    )


def _base_record(
    key: str, question: Question, task: Task, condition: str, model: ModelConfig
) -> dict[str, Any]:
    return {
        "key": key,
        "set": question.set_name,
        "qid": question.qid,
        "task": task.value,
        "condition": condition,
        "model_name": model.name,
        "model_id": model.model_id,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _log_error(folder: Path, key: str, result: ChatResult) -> None:
    with (folder / "errors.log").open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {key}: {result.error}\n")
    print(f"   ERROR {key}: {(result.error or '')[:160]}")


def pushback_conditions(
    question: Question,
    *,
    set_name: str,
    config: ProjectConfig,
    lines: list[PushbackLine],
) -> list[tuple[str, str]]:
    """(condition, pushback text) pairs for Task B on this set."""
    conditions = [(Condition.STANDARD.value, question.pushback)]
    if lines and set_name == config.set4.applies_to:
        conditions += [(line.pid, line.text_bn) for line in lines]
    return conditions


def expected_keys(
    questions: list[Question],
    *,
    set_name: str,
    tasks: list[Task],
    config: ProjectConfig,
    lines: list[PushbackLine],
) -> list[str]:
    keys = []
    for q in questions:
        if Task.SUGGESTED_ANSWER in tasks:
            for cond in (Condition.PLAIN, Condition.WRONG_GUESS):
                keys.append(f"{Task.SUGGESTED_ANSWER.value}|{q.qid}|{cond.value}")
        if Task.ARE_YOU_SURE in tasks:
            keys.append(f"{Task.ARE_YOU_SURE.value}|{q.qid}|{Condition.TURN1.value}")
            for cond, _ in pushback_conditions(
                q, set_name=set_name, config=config, lines=lines
            ):
                keys.append(f"{Task.ARE_YOU_SURE.value}|{q.qid}|{cond}")
    return keys


def run_question(
    question: Question,
    *,
    model: ModelConfig,
    tasks: list[Task],
    conditions: list[tuple[str, str]],
    saved: dict[str, dict[str, Any]],
    out_file: Path,
    tally: RunTally,
) -> None:
    answers = (question.correct, question.wrong)
    folder = out_file.parent

    def ask(messages: list[dict[str, str]], key: str) -> ChatResult:
        result = call_model(model, messages, answers=answers)
        tally.add(result)
        if not result.ok:
            _log_error(folder, key, result)
        return result

    if Task.SUGGESTED_ANSWER in tasks:
        for cond, prompt in (
            (Condition.PLAIN, question.prompt_plain),
            (Condition.WRONG_GUESS, question.prompt_wrong_guess),
        ):
            key = f"{Task.SUGGESTED_ANSWER.value}|{question.qid}|{cond.value}"
            if key in saved or tally.stopped:
                continue
            messages = [{"role": "user", "content": prompt}]
            result = ask(messages, key)
            if result.ok:
                record = _base_record(
                    key, question, Task.SUGGESTED_ANSWER, cond.value, model
                )
                record.update(
                    messages=messages,
                    reply=result.text,
                    temperature_used=result.temperature_used,
                    stop=result.stop_reason,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
                _append_jsonl(out_file, record)
                saved[key] = record

    if Task.ARE_YOU_SURE not in tasks:
        return
    turn1 = [{"role": "user", "content": question.prompt_ays_turn1}]
    key1 = f"{Task.ARE_YOU_SURE.value}|{question.qid}|{Condition.TURN1.value}"
    if key1 not in saved and not tally.stopped:
        result = ask(turn1, key1)
        if not result.ok:
            return
        record = _base_record(
            key1, question, Task.ARE_YOU_SURE, Condition.TURN1.value, model
        )
        record.update(
            messages=turn1,
            reply=result.text,
            temperature_used=result.temperature_used,
            stop=result.stop_reason,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        _append_jsonl(out_file, record)
        saved[key1] = record
    if key1 not in saved:
        return
    first_text = saved[key1]["reply"]

    for cond, push in conditions:
        key = f"{Task.ARE_YOU_SURE.value}|{question.qid}|{cond}"
        if key in saved or tally.stopped:
            continue
        turn2 = turn1 + [
            {"role": "assistant", "content": first_text},
            {"role": "user", "content": push},
        ]
        second = ask(turn2, key)
        if not second.ok:
            continue
        turn3 = turn2 + [
            {"role": "assistant", "content": second.text},
            {"role": "user", "content": question.final_ask},
        ]
        final = ask(turn3, key)
        if not final.ok:
            continue
        record = _base_record(key, question, Task.ARE_YOU_SURE, cond, model)
        record.update(
            messages=turn3,
            first_reply=first_text,
            second_reply=second.text,
            final_reply=final.text,
            temperature_used=final.temperature_used,
            stop_second=second.stop_reason,
            stop_final=final.stop_reason,
            input_tokens=(second.input_tokens or 0) + (final.input_tokens or 0),
            output_tokens=(second.output_tokens or 0) + (final.output_tokens or 0),
        )
        _append_jsonl(out_file, record)
        saved[key] = record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one model on the question sets.")
    parser.add_argument("--model", required=True, help="a model name from config.yaml")
    parser.add_argument("--sets", nargs="*", default=None, help="default: all four")
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=[t.value for t in Task],
        choices=[t.value for t in Task],
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="pilot: first N questions"
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--outputs", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    model = config.get_model(args.model)
    if model.is_placeholder:
        raise ConfigError(f"Set the model id for '{model.name}' in config.yaml first.")
    check_credentials(model)
    tasks = [Task(t) for t in args.tasks]
    set_names = args.sets or list(config.sets)
    unknown = [s for s in set_names if s not in config.sets]
    if unknown:
        raise ConfigError(f"Unknown sets: {', '.join(unknown)}")
    lines = load_pushback_lines(config.set4.path) if config.set4.enabled else []

    folder = resolve_outputs(model, args.outputs) / "runs" / model.name
    folder.mkdir(parents=True, exist_ok=True)
    args.sets = set_names
    write_run_log(folder, model, args)
    tally = RunTally()
    summary = []

    for set_name in set_names:
        questions = load_questions(config.sets[set_name])
        if args.limit:
            questions = select_pilot(questions, limit=args.limit)
        out_file = folder / f"{set_name}.jsonl"
        saved = load_saved(out_file)
        print(f"\n== {model.name} | {set_name} | {len(questions)} questions")
        for i, question in enumerate(questions, 1):
            conditions = pushback_conditions(
                question, set_name=set_name, config=config, lines=lines
            )
            run_question(
                question,
                model=model,
                tasks=tasks,
                conditions=conditions,
                saved=saved,
                out_file=out_file,
                tally=tally,
            )
            if i % 10 == 0 or i == len(questions):
                print(f"   {i}/{len(questions)} questions | {tally.format_line()}")
            if tally.stopped:
                break
        keys = expected_keys(
            questions, set_name=set_name, tasks=tasks, config=config, lines=lines
        )
        done = sum(1 for k in keys if k in saved)
        summary.append((set_name, done, len(keys)))
        if tally.stopped:
            break

    print(f"\nThis session: {tally.format_line()}")
    print("Saved records (done / expected):")
    for set_name, done, expected in summary:
        status = "complete" if done == expected else "NOT complete, run again"
        print(f"   {set_name}: {done} / {expected}  {status}")
    if tally.stopped:
        print(
            f"\nStopped after {MAX_CONSECUTIVE_ERRORS} failed calls in a row. "
            f"Read {folder / 'errors.log'}, fix the cause, then run the same command."
        )
        return 1
    complete = all(done == expected for _, done, expected in summary)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
