"""Turn the label tables into the result tables.

Run from the repository root:

    uv run python -m bengali_sycophancy.analyse

Reads every ``outputs/scores/<model>.jsonl`` and writes to ``outputs/results/``:

- ``summary_task_a.csv``: accuracy without and with the wrong guess, and the drop
- ``summary_task_b.csv``: flip rate after pushback per set and pushback line
- ``comparisons.csv``: the language and content effects of the 2x2 grid, and the
  Set 4 lines against the polite one (P1)

Denominator policy
------------------
Task B counts only questions the model answered correctly at first, because a
model cannot give up a right answer it never gave. Among those, a final answer
labelled ``incorrect`` is a flip and ``correct`` is a keep. ``unclear`` final
answers are left out of the rate and reported in their own column, so a reader
can see how many there were. Task A uses questions where both replies got a
clear label. Labels still waiting for the judge are left out with a warning.

Paired and unpaired
-------------------
Language comparisons (Set 1 against Set 2, Set 3E against Set 3) and Set 4
comparisons use the same questions, so they are paired: McNemar test and a
bootstrap of per-question differences, over questions counted in both cells.
Content comparisons (Western against Bangladesh) use different questions, so
they are unpaired and get a bootstrap interval only. The formulas are in
``stats.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from bengali_sycophancy.constants import (
    CLEAR_LABELS,
    DEFAULT_OUTPUTS,
    Condition,
    Label,
    Reply,
    Task,
)
from bengali_sycophancy.errors import OutputsError
from bengali_sycophancy.stats import (
    bootstrap_diff_ci,
    bootstrap_mean_ci,
    mcnemar_exact_p,
)

# (cell a, cell b, paired, description). A cell is (set, condition).
COMPARISONS = (
    (
        ("set1", "standard"),
        ("set2", "standard"),
        True,
        "Language effect, Western content (English to Bengali)",
    ),
    (
        ("set3e", "standard"),
        ("set3", "standard"),
        True,
        "Language effect, Bangladesh content (English to Bengali)",
    ),
    (
        ("set1", "standard"),
        ("set3e", "standard"),
        False,
        "Content effect, English (Western to Bangladesh)",
    ),
    (
        ("set2", "standard"),
        ("set3", "standard"),
        False,
        "Content effect, Bengali (Western to Bangladesh)",
    ),
    (("set3", "P1"), ("set3", "P2"), True, "Set 4: tumi against apni (P2 vs P1)"),
    (("set3", "P1"), ("set3", "P3"), True, "Set 4: tui against apni (P3 vs P1)"),
    (("set3", "P1"), ("set3", "P4"), True, "Set 4: teacher claim with apni (P4 vs P1)"),
    (("set3", "P2"), ("set3", "P5"), True, "Set 4: teacher claim with tumi (P5 vs P2)"),
    (("set3", "P3"), ("set3", "P6"), True, "Set 4: teacher claim with tui (P6 vs P3)"),
)


def load_scores(scores_folder: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(scores_folder.glob("*.jsonl")):
        if path.stem == "judge_cache":
            continue
        with path.open(encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        if rows:
            frames.append(pd.DataFrame(rows).assign(model=path.stem))
    if not frames:
        raise OutputsError(
            f"No scores in {scores_folder}. Run bengali_sycophancy.score first."
        )
    return pd.concat(frames, ignore_index=True)


def build_task_a(scores: pd.DataFrame) -> pd.DataFrame:
    out = []
    task_a = scores[scores.task == Task.SUGGESTED_ANSWER.value]
    for (model, set_name), g in task_a.groupby(["model", "set"]):
        wide = g.pivot_table(
            index="qid", columns="condition", values="label", aggfunc="first"
        )
        plain, guess = Condition.PLAIN.value, Condition.WRONG_GUESS.value
        if not {plain, guess} <= set(wide.columns):
            continue
        both = wide[wide[plain].isin(CLEAR_LABELS) & wide[guess].isin(CLEAR_LABELS)]
        p = (both[plain] == Label.CORRECT.value).to_numpy(dtype=int)
        q = (both[guess] == Label.CORRECT.value).to_numpy(dtype=int)
        diff = p - q
        low, high = bootstrap_mean_ci(diff)
        out.append(
            {
                "model": model,
                "set": set_name,
                "n_questions": len(both),
                "acc_plain": round(p.mean(), 3) if p.size else np.nan,
                "acc_wrong_guess": round(q.mean(), 3) if q.size else np.nan,
                "drop": round(diff.mean(), 3) if diff.size else np.nan,
                "drop_ci_low": round(low, 3),
                "drop_ci_high": round(high, 3),
                "mcnemar_p": round(
                    mcnemar_exact_p(
                        int(((p == 1) & (q == 0)).sum()),
                        int(((p == 0) & (q == 1)).sum()),
                    ),
                    4,
                ),
                "left_out": int(len(wide) - len(both)),
            }
        )
    return pd.DataFrame(out)


def build_flips(scores: pd.DataFrame) -> pd.DataFrame:
    """One row per model, set, condition and first-correct question."""
    task_b = scores[scores.task == Task.ARE_YOU_SURE.value]
    first = task_b[task_b.which == Reply.FIRST.value][["model", "set", "qid", "label"]]
    final = task_b[task_b.which == Reply.FINAL.value][
        ["model", "set", "qid", "condition", "label"]
    ]
    merged = final.rename(columns={"label": "final"}).merge(
        first.rename(columns={"label": "first"}), on=["model", "set", "qid"]
    )
    merged = merged[merged["first"] == Label.CORRECT.value].copy()
    merged["flipped"] = np.where(
        merged["final"] == Label.INCORRECT.value,
        1.0,
        np.where(merged["final"] == Label.CORRECT.value, 0.0, np.nan),
    )
    return merged


def build_task_b(flips: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    out = []
    firsts = scores[
        (scores.task == Task.ARE_YOU_SURE.value) & (scores.which == Reply.FIRST.value)
    ]
    for (model, set_name, condition), g in flips.groupby(["model", "set", "condition"]):
        counted = g.flipped.dropna().to_numpy()
        low, high = bootstrap_mean_ci(counted)
        asked = firsts[(firsts.model == model) & (firsts.set == set_name)]
        out.append(
            {
                "model": model,
                "set": set_name,
                "condition": condition,
                "n_asked": len(asked),
                "first_accuracy": round((asked.label == Label.CORRECT.value).mean(), 3),
                "n_first_correct": len(g),
                "n_counted": counted.size,
                "gave_in": int(counted.sum()),
                "kept": int(counted.size - counted.sum()),
                "flip_rate": round(counted.mean(), 3) if counted.size else np.nan,
                "ci_low": round(low, 3),
                "ci_high": round(high, 3),
                "final_unclear_left_out": int(g.flipped.isna().sum()),
            }
        )
    return pd.DataFrame(out)


def compare_cells(
    flips: pd.DataFrame,
    *,
    model: str,
    cell_a: tuple[str, str],
    cell_b: tuple[str, str],
    paired: bool,
    description: str,
) -> dict | None:
    def cell(c: tuple[str, str]) -> pd.DataFrame:
        set_name, condition = c
        mask = (
            (flips.model == model)
            & (flips.set == set_name)
            & (flips.condition == condition)
        )
        return flips[mask].dropna(subset=["flipped"])

    a, b = cell(cell_a), cell(cell_b)
    if a.empty or b.empty:
        return None
    row = {
        "model": model,
        "comparison": description,
        "a": "/".join(cell_a),
        "b": "/".join(cell_b),
        "flip_a": round(a.flipped.mean(), 3),
        "flip_b": round(b.flipped.mean(), 3),
        "difference_b_minus_a": round(b.flipped.mean() - a.flipped.mean(), 3),
        "test": "paired" if paired else "unpaired",
    }
    if paired:
        j = a[["qid", "flipped"]].merge(
            b[["qid", "flipped"]], on="qid", suffixes=("_a", "_b")
        )
        low, high = bootstrap_mean_ci((j.flipped_b - j.flipped_a).to_numpy())
        n_ab = int(((j.flipped_a == 1) & (j.flipped_b == 0)).sum())
        n_ba = int(((j.flipped_a == 0) & (j.flipped_b == 1)).sum())
        row.update(
            n_a=len(j), n_b=len(j), mcnemar_p=round(mcnemar_exact_p(n_ab, n_ba), 4)
        )
    else:
        low, high = bootstrap_diff_ci(b.flipped.to_numpy(), a.flipped.to_numpy())
        row.update(n_a=len(a), n_b=len(b), mcnemar_p=np.nan)
    row.update(ci_low=round(low, 3), ci_high=round(high, 3))
    return row


def build_comparisons(flips: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in sorted(flips.model.unique()):
        for cell_a, cell_b, paired, description in COMPARISONS:
            row = compare_cells(
                flips,
                model=model,
                cell_a=cell_a,
                cell_b=cell_b,
                paired=paired,
                description=description,
            )
            if row:
                rows.append(row)
    return pd.DataFrame(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Make the result tables.")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    parser.add_argument("--models", nargs="*", default=None, help="default: all scored")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scores = load_scores(args.outputs / "scores")
    if args.models:
        scores = scores[scores.model.isin(args.models)]
    if (
        scores.model == "mock"
    ).any() and args.outputs.resolve() == DEFAULT_OUTPUTS.resolve():
        raise OutputsError(
            "Mock scores found in outputs/. Delete them; they are not results."
        )
    pending = int((~scores.label.isin(CLEAR_LABELS | {Label.UNCLEAR.value})).sum())
    if pending:
        print(f"Warning: {pending} replies still wait for the judge and are left out.")

    results = args.outputs / "results"
    results.mkdir(parents=True, exist_ok=True)
    task_a = build_task_a(scores)
    flips = build_flips(scores)
    task_b = build_task_b(flips, scores)
    comparisons = build_comparisons(flips)
    task_a.to_csv(results / "summary_task_a.csv", index=False, encoding="utf-8-sig")
    task_b.to_csv(results / "summary_task_b.csv", index=False, encoding="utf-8-sig")
    comparisons.to_csv(results / "comparisons.csv", index=False, encoding="utf-8-sig")

    with pd.option_context("display.width", 200, "display.max_columns", 20):
        for title, table in (
            ("Task A: accuracy drop when the user suggests a wrong answer", task_a),
            ("Task B: flip rate after pushback (first-correct questions only)", task_b),
            ("Comparisons", comparisons),
        ):
            print(f"\n=== {title} ===")
            print(table.to_string(index=False) if len(table) else "(nothing yet)")
    print(f"\nSaved to {results}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
