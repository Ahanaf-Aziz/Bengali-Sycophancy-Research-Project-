"""Check the judge model against a human's labels.

Run from the repository root, after every model is scored:

    uv run python -m bengali_sycophancy.check_judge export --n 200
    uv run python -m bengali_sycophancy.check_judge compare

``export`` draws a random sample (fixed seed) of judge-labelled replies from all
models and writes ``outputs/results/judge_check.csv``. The judge's label is in
the last column, ``judge_label_hidden``: hide it before labelling. Fill
``human_label`` with correct, incorrect or unclear (any letter case) and save as
CSV UTF-8. ``compare`` prints agreement, Cohen's kappa and every disagreement,
and writes the numbers to ``outputs/results/judge_agreement.json``.

Why a human check
-----------------
The judge decides the hardest replies. A native speaker's labels are the only
direct evidence that it grades Bengali replies correctly. Kappa of about 0.8 or
more is usually read as strong agreement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from bengali_sycophancy.config import load_config
from bengali_sycophancy.constants import (
    DEFAULT_OUTPUTS,
    JUDGE_SAMPLE_SEED,
    Label,
    Method,
)
from bengali_sycophancy.errors import OutputsError
from bengali_sycophancy.score import load_question_index
from bengali_sycophancy.stats import cohen_kappa

HUMAN_LABELS = (Label.CORRECT.value, Label.INCORRECT.value, Label.UNCLEAR.value)


def export_sheet(*, outputs: Path, config_path: Path, n: int) -> Path:
    rows = []
    for path in sorted((outputs / "scores").glob("*.jsonl")):
        if path.stem == "judge_cache":
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r["method"] == Method.JUDGE.value and r["label"] in HUMAN_LABELS:
                        rows.append({**r, "model": path.stem})
    if not rows:
        raise OutputsError("No judge-labelled replies yet. Score with the judge first.")
    sample = pd.DataFrame(rows).sample(
        n=min(n, len(rows)), random_state=JUDGE_SAMPLE_SEED
    )
    questions = load_question_index(load_config(config_path))
    info = [questions[(s, q)] for s, q in zip(sample["set"], sample["qid"])]
    sheet = pd.DataFrame(
        {
            "model": sample["model"].to_numpy(),
            "set": sample["set"].to_numpy(),
            "qid": sample["qid"].to_numpy(),
            "key": sample["key"].to_numpy(),
            "which": sample["which"].to_numpy(),
            "question": [q.question for q in info],
            "correct_answers": [" | ".join(q.all_correct()) for q in info],
            "wrong_answer": [q.wrong for q in info],
            "reply": sample["reply"].to_numpy(),
            "human_label": "",
            "judge_label_hidden": sample["label"].to_numpy(),
        }
    )
    path = outputs / "results" / "judge_check.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def compare_sheet(*, outputs: Path) -> dict[str, float | int]:
    path = outputs / "results" / "judge_check.csv"
    if not path.exists():
        raise OutputsError(f"{path} not found. Run 'export' first.")
    sheet = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    sheet["human_label"] = sheet["human_label"].str.strip().str.lower()
    labelled = sheet[sheet["human_label"].isin(HUMAN_LABELS)]
    if labelled.empty:
        raise OutputsError("No human labels yet. Fill the human_label column first.")
    human = labelled["human_label"].tolist()
    judge = labelled["judge_label_hidden"].str.lower().tolist()
    agreement = sum(h == j for h, j in zip(human, judge)) / len(human)
    kappa = cohen_kappa(human, judge)
    print(f"Rows compared: {len(human)} of {len(sheet)}")
    print(f"Agreement: {agreement:.3f}")
    print(f"Cohen's kappa: {kappa:.3f}")
    print("\nHuman (rows) against judge (columns):")
    print(pd.crosstab(pd.Series(human, name="human"), pd.Series(judge, name="judge")))
    disagree = labelled[
        labelled["human_label"] != labelled["judge_label_hidden"].str.lower()
    ]
    if not disagree.empty:
        print("\nDisagreements, worth reading one by one:")
        print(
            disagree[["qid", "reply", "human_label", "judge_label_hidden"]].to_string(
                index=False
            )
        )
    summary = {
        "rows_compared": len(human),
        "agreement": round(agreement, 4),
        "kappa": round(kappa, 4),
    }
    with (outputs / "results" / "judge_agreement.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(summary, f, indent=2)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the judge against human labels."
    )
    parser.add_argument("step", choices=["export", "compare"])
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.step == "export":
        path = export_sheet(outputs=args.outputs, config_path=args.config, n=args.n)
        print(f"Wrote {path}. Hide judge_label_hidden, then fill human_label.")
    else:
        compare_sheet(outputs=args.outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
