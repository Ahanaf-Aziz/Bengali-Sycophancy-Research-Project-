"""Turn saved replies into one tidy table of labels per model.

Run from the repository root:

    uv run python -m bengali_sycophancy.score --model claude

Reads ``outputs/runs/<model>/*.jsonl`` and writes ``outputs/scores/<model>.jsonl``
with one line per scored reply: set, question id, task, condition, which reply,
the reply text, its label and how the label was given (``rule`` or ``judge``).
The rules are in ``scoring.py``.

What is scored
--------------
Task A: each reply. Task B: the first answer and the final answer after
pushback. The analysis uses the first answer to decide which questions count.

Judge cache
-----------
Judge labels are cached in ``outputs/scores/judge_cache.jsonl`` by judge model,
set, question and exact reply text, so an identical reply is never paid for
twice, across models too. A failed judge call is labelled ``judge_error``, not
cached, and retried on the next run, as are ``needs_judge`` labels left by
``--no-judge``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bengali_sycophancy.config import ModelConfig, ProjectConfig, load_config
from bengali_sycophancy.constants import (
    RETRY_LABELS,
    Condition,
    Label,
    Method,
    Reply,
    Task,
)
from bengali_sycophancy.dataset import Question, load_questions
from bengali_sycophancy.errors import OutputsError
from bengali_sycophancy.providers import call_model, check_credentials
from bengali_sycophancy.run import load_saved, resolve_outputs
from bengali_sycophancy.scoring import (
    build_judge_prompt,
    mock_judge_label,
    parse_judge_output,
    rule_label,
)

Judge = Callable[[str, Question], Label]


def make_judge(judge_model: ModelConfig) -> Judge:
    check_credentials(judge_model)

    def judge(reply: str, question: Question) -> Label:
        prompt = build_judge_prompt(reply, question)
        result = call_model(judge_model, [{"role": "user", "content": prompt}])
        if not result.ok:
            error = (result.error or "")[:120]
            print(f"    Judge call failed for {question.qid}: {error}")
            return Label.JUDGE_ERROR
        label = parse_judge_output(result.text)
        if label is None:
            print(f"    Judge gave no label for {question.qid}: {result.text[:80]!r}")
            return Label.JUDGE_ERROR
        return label

    return judge


def replies_to_score(record: dict[str, Any]) -> list[tuple[Reply, str]]:
    if record["task"] == Task.SUGGESTED_ANSWER.value:
        return [(Reply.ANSWER, record["reply"])]
    if record["condition"] == Condition.TURN1.value:
        return [(Reply.FIRST, record["reply"])]
    return [(Reply.FINAL, record["final_reply"])]


def load_question_index(config: ProjectConfig) -> dict[tuple[str, str], Question]:
    index = {}
    for set_name, spec in config.sets.items():
        for q in load_questions(spec):
            index[(set_name, q.qid)] = q
    return index


def load_cache(path: Path) -> dict[tuple[str, str, str, str], str]:
    cache: dict[tuple[str, str, str, str], str] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    cache[(c["judge"], c["set"], c["qid"], c["reply"])] = c["label"]
    return cache


def score_model(
    *,
    runs_folder: Path,
    scores_path: Path,
    cache_path: Path,
    questions: dict[tuple[str, str], Question],
    judge: Judge | None,
    judge_id: str | None,
) -> tuple[dict[str, int], int]:
    """Score every reply not yet scored.

    Returns the counts of new labels and the number of replies, old or new,
    still waiting for the judge.
    """
    scored: dict[tuple[str, str, str], dict[str, Any]] = {}
    if scores_path.exists():
        with scores_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    scored[(r["set"], r["key"], r["which"])] = r
    cache = load_cache(cache_path)
    counts: dict[str, int] = {}

    for run_file in sorted(runs_folder.glob("*.jsonl")):
        if run_file.name == "run_log.jsonl":
            continue
        for record in load_saved(run_file).values():
            question = questions[(record["set"], record["qid"])]
            for which, reply in replies_to_score(record):
                key = (record["set"], record["key"], which.value)
                old = scored.get(key)
                if old and not (old["label"] in RETRY_LABELS and judge):
                    continue
                label, method = rule_label(reply, question), Method.RULE
                if label is None:
                    if judge is None:
                        label, method = Label.NEEDS_JUDGE, Method.NONE
                    else:
                        method = Method.JUDGE
                        ck = (judge_id or "", record["set"], record["qid"], reply)
                        if ck in cache:
                            label = Label(cache[ck])
                        else:
                            label = judge(reply, question)
                            if label is not Label.JUDGE_ERROR:
                                cache[ck] = label.value
                                with cache_path.open("a", encoding="utf-8") as f:
                                    f.write(
                                        json.dumps(
                                            {
                                                "judge": ck[0],
                                                "set": ck[1],
                                                "qid": ck[2],
                                                "reply": reply,
                                                "label": label.value,
                                            },
                                            ensure_ascii=False,
                                        )
                                        + "\n"
                                    )
                scored[key] = {
                    "key": record["key"],
                    "set": record["set"],
                    "qid": record["qid"],
                    "task": record["task"],
                    "condition": record["condition"],
                    "which": which.value,
                    "reply": reply,
                    "label": label.value,
                    "method": method.value,
                    "judge": judge_id if method is Method.JUDGE else None,
                }
                counts[label.value] = counts.get(label.value, 0) + 1

    with scores_path.open("w", encoding="utf-8") as f:
        for row in scored.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    pending = sum(1 for row in scored.values() if row["label"] in RETRY_LABELS)
    return counts, pending


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Label every saved reply.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--no-judge", action="store_true", help="rules only, free")
    parser.add_argument("--judge", choices=["config", "mock"], default="config")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--outputs", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    model = config.get_model(args.model)
    outputs = resolve_outputs(model, args.outputs)
    runs_folder = outputs / "runs" / model.name
    if not any(runs_folder.glob("set*.jsonl")):
        raise OutputsError(
            f"No replies in {runs_folder}. Run bengali_sycophancy.run first."
        )

    judge: Judge | None = None
    judge_id: str | None = None
    if not args.no_judge:
        if args.judge == "mock":
            judge, judge_id = mock_judge_label, "mock-judge"
        else:
            judge, judge_id = make_judge(config.judge), config.judge.model_id

    scores_folder = outputs / "scores"
    scores_folder.mkdir(parents=True, exist_ok=True)
    counts, pending = score_model(
        runs_folder=runs_folder,
        scores_path=scores_folder / f"{model.name}.jsonl",
        cache_path=scores_folder / "judge_cache.jsonl",
        questions=load_question_index(config),
        judge=judge,
        judge_id=judge_id,
    )
    print(f"Scored {sum(counts.values())} new replies for {model.name}: {counts}")
    if pending:
        print(f"{pending} replies still need the judge. Run the same command again.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
