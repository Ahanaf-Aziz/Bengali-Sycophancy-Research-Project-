"""Check the labels that drive the results with a second, blind judge.

Run from the repository root, after every model is scored:

    uv run python -m bengali_sycophancy.check_labels auto

``auto`` collects three groups of replies from every score file:

- ``sway``: Task A wrong_guess replies labelled incorrect where the same model's
  plain answer to that question was correct (all sets).
- ``flip``: Task B final replies labelled incorrect where the first answer was
  correct (all sets and conditions).
- ``no_sway``: a random sample (seed 0) of 60 Bengali and 60 English Task A
  wrong_guess replies labelled correct where plain was correct.

A second judge (``judge2`` in ``config.yaml``) labels each reply with the same
prompt as the first judge. It never sees the first label. Its answers are cached
in ``outputs/results/judge2_cache.jsonl`` by judge model, set, question and exact
reply, so a rerun never pays twice. A failed call is labelled ``judge_error``, not
cached, and retried on the next run. The table is written to
``outputs/results/label_check_auto.csv``. Nothing in ``outputs/scores`` changes.

The cache is kept out of ``outputs/scores``, because ``analyse`` and
``check_judge`` read every ``.jsonl`` file there as a model's scores.
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from bengali_sycophancy import analyse
from bengali_sycophancy.config import load_config
from bengali_sycophancy.constants import DEFAULT_OUTPUTS, RNG_SEED, Label
from bengali_sycophancy.score import load_cache, load_question_index, make_judge
from bengali_sycophancy.scoring import mock_judge_label

BENGALI_SETS = {"set2", "set3"}
NO_SWAY_PER_LANGUAGE = 60
WORKERS = 4


def collect(scores: pd.DataFrame) -> pd.DataFrame:
    ta = scores[scores.task == "suggested_answer"]
    plain = ta[ta.condition == "plain"][["model", "set", "qid", "label"]]
    guess = ta[ta.condition == "wrong_guess"].merge(
        plain.rename(columns={"label": "plain_label"}), on=["model", "set", "qid"]
    )
    guess = guess[guess.plain_label == "correct"]
    sway = guess[guess.label == "incorrect"].assign(group="sway")

    flips = analyse.build_flips(scores)
    flips = flips[flips.flipped == 1][["model", "set", "qid", "condition"]]
    final = scores[(scores.task == "are_you_sure") & (scores.which == "final")]
    flip = final.merge(flips, on=["model", "set", "qid", "condition"]).assign(group="flip")

    held = guess[guess.label == "correct"].copy()
    held["language"] = held.set.map(lambda s: "BN" if s in BENGALI_SETS else "EN")
    no_sway = pd.concat(
        g.sample(n=min(NO_SWAY_PER_LANGUAGE, len(g)), random_state=RNG_SEED)
        for _, g in held.sort_values(["model", "set", "key"]).groupby("language")
    ).assign(group="no_sway")

    rows = pd.concat([sway, flip, no_sway], ignore_index=True)
    rows["language"] = rows.set.map(lambda s: "BN" if s in BENGALI_SETS else "EN")
    return rows


def run_auto(*, outputs: Path, config_path: Path, judge_name: str, limit: int | None) -> Path:
    config = load_config(config_path)
    judge_model = config.get_model(judge_name)
    questions = load_question_index(config)
    rows = collect(analyse.load_scores(outputs / "scores"))
    if limit:
        rows = rows.groupby("group").head(limit).reset_index(drop=True)

    cache_path = outputs / "results" / "judge2_cache.jsonl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)
    judge_id = judge_model.model_id
    keys = [(judge_id, s, q, r) for s, q, r in zip(rows.set, rows.qid, rows.reply)]
    todo = list(dict.fromkeys(k for k in keys if k not in cache))
    print(f"{len(rows)} rows: {rows.group.value_counts().to_dict()}")
    print(f"{len(set(keys))} distinct replies: {len(set(keys)) - len(todo)} already "
          f"cached, {len(todo)} to ask {judge_id}")

    if judge_model.provider.value == "mock":
        def judge(reply, question):
            return mock_judge_label(reply, question)
    else:
        judge = make_judge(judge_model)
    lock = threading.Lock()
    errors = 0

    def ask(k):
        return k, judge(k[3], questions[(k[1], k[2])])

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(ask, k) for k in todo]
        for done, fut in enumerate(as_completed(futures), 1):
            k, label = fut.result()
            if label is Label.JUDGE_ERROR:
                errors += 1
            else:
                with lock:
                    cache[k] = label.value
                    with cache_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"judge": k[0], "set": k[1], "qid": k[2],
                                            "reply": k[3], "label": label.value},
                                           ensure_ascii=False) + "\n")
            if done % 25 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} done, {errors} errors", flush=True)

    info = [questions[(s, q)] for s, q in zip(rows.set, rows.qid)]
    sheet = pd.DataFrame({
        "model": rows.model, "set": rows.set, "qid": rows.qid, "key": rows.key,
        "which": rows.which, "language": rows.language, "group": rows.group,
        "method": rows.method, "auto_label": rows.label,
        "judge2_label": [cache.get(k, Label.JUDGE_ERROR.value) for k in keys],
        "question": [q.question for q in info],
        "correct_answers": [" | ".join(q.all_correct()) for q in info],
        "wrong_answer": [q.wrong for q in info],
        "reply": rows.reply,
    })
    path = outputs / "results" / "label_check_auto.csv"
    sheet.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Judge errors this run: {errors} (retried on the next run)")
    print(pd.crosstab([sheet.group, sheet.language], sheet.auto_label != sheet.judge2_label,
                      margins=True).rename(columns={False: "agree", True: "disagree"}))
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check labels with a second judge.")
    parser.add_argument("step", choices=["auto"])
    parser.add_argument("--judge", default="judge2", help="model name in config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="rows per group (tests)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = run_auto(outputs=args.outputs, config_path=args.config,
                    judge_name=args.judge, limit=args.limit)
    print(f"Wrote {path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
