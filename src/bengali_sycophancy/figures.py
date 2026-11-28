"""Draw the result figures from the result tables.

Run from the repository root, after ``bengali_sycophancy.analyse``:

    uv run python -m bengali_sycophancy.figures

Reads ``outputs/results/*.csv`` and writes a PDF and a PNG per figure to
``outputs/figures/``. Every point is a rate with its 95% bootstrap interval.

Figure ownership
----------------
One generator per stem. If a figure changes meaning, change its stem, its
generator and this table together.

======  ==========================  ==============================================
Prefix  Stem                        Shows
======  ==========================  ==============================================
a\\_     a_accuracy_drop             Task A: accuracy drop per set and model
b\\_     b_flip_rate_by_set          Task B: flip rate per set, standard pushback
p\\_     p_pushback_forms            Set 4: flip rate per pushback line on Set 3
======  ==========================  ==============================================
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bengali_sycophancy.constants import DEFAULT_OUTPUTS, Condition
from bengali_sycophancy.errors import OutputsError
from bengali_sycophancy.style import (
    DOUBLE_COLUMN_IN,
    PALETTE,
    apply_style,
    model_colour,
    model_marker,
    model_name,
    save_figure_pair,
)

SET_ORDER = ("set1", "set2", "set3e", "set3")
SET_LABELS = {
    "set1": "Set 1\nWestern, English",
    "set2": "Set 2\nWestern, Bengali",
    "set3e": "Set 3E\nBangladesh, English",
    "set3": "Set 3\nBangladesh, Bengali",
}
PUSHBACK_ORDER = ("P1", "P2", "P3", "P4", "P5", "P6")
PUSHBACK_LABELS = {
    "P1": "P1\napni",
    "P2": "P2\ntumi",
    "P3": "P3\ntui",
    "P4": "P4\napni +\nteacher",
    "P5": "P5\ntumi +\nteacher",
    "P6": "P6\ntui +\nteacher",
}
GROUP_WIDTH = 0.8  # share of the gap between x positions used by one group


def plot_points(
    table: pd.DataFrame,
    *,
    x_column: str,
    x_order: tuple[str, ...],
    x_labels: dict[str, str],
    y_column: str,
    low_column: str,
    high_column: str,
    y_label: str,
    title: str,
    figsize: tuple[float, float],
) -> plt.Figure:
    """Points with 95% whiskers, one colour and marker per model, side by side."""
    if table.empty:
        raise ValueError(f"No rows to plot for '{title}'.")
    x_values = [x for x in x_order if x in set(table[x_column])]
    models = sorted(table.model.unique())
    fig, ax = plt.subplots(figsize=figsize)
    dodge = GROUP_WIDTH / len(models)
    offsets = (np.arange(len(models)) - (len(models) - 1) / 2) * dodge
    for i, model in enumerate(models):
        rows = table[table.model == model].set_index(x_column).reindex(x_values)
        xs = np.arange(len(x_values)) + offsets[i]
        y = rows[y_column].to_numpy(dtype=float)
        err = np.vstack(
            [
                y - rows[low_column].to_numpy(dtype=float),
                rows[high_column].to_numpy(dtype=float) - y,
            ]
        )
        ax.errorbar(
            xs,
            y,
            yerr=err,
            fmt=model_marker(model),
            capsize=3,
            markersize=5,
            color=model_colour(model, i),
            label=model_name(model),
        )
    ax.axhline(0, color=PALETTE["grey"], linewidth=0.8)
    ax.set_xticks(np.arange(len(x_values)))
    ax.set_xticklabels([x_labels[x] for x in x_values])
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return fig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Draw the result figures.")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = args.outputs / "results"
    figures = args.outputs / "figures"
    paths = {
        name: results / f"{name}.csv" for name in ("summary_task_a", "summary_task_b")
    }
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise OutputsError(
            f"Missing {', '.join(missing)}. Run bengali_sycophancy.analyse."
        )
    apply_style()
    task_a = pd.read_csv(paths["summary_task_a"], encoding="utf-8-sig")
    task_b = pd.read_csv(paths["summary_task_b"], encoding="utf-8-sig")
    size = (DOUBLE_COLUMN_IN, 3.0)

    fig = plot_points(
        task_a,
        x_column="set",
        x_order=SET_ORDER,
        x_labels=SET_LABELS,
        y_column="drop",
        low_column="drop_ci_low",
        high_column="drop_ci_high",
        y_label="Accuracy drop with a wrong guess",
        title="Task A: how much a suggested wrong answer lowers accuracy",
        figsize=size,
    )
    save_figure_pair(fig, figures / "a_accuracy_drop")
    plt.close(fig)

    standard = task_b[task_b.condition == Condition.STANDARD.value]
    fig = plot_points(
        standard,
        x_column="set",
        x_order=SET_ORDER,
        x_labels=SET_LABELS,
        y_column="flip_rate",
        low_column="ci_low",
        high_column="ci_high",
        y_label="Flip rate after pushback",
        title="Task B: share of correct first answers given up after pushback",
        figsize=size,
    )
    save_figure_pair(fig, figures / "b_flip_rate_by_set")
    plt.close(fig)

    set4 = task_b[task_b.condition.isin(PUSHBACK_ORDER)]
    if not set4.empty:
        fig = plot_points(
            set4,
            x_column="condition",
            x_order=PUSHBACK_ORDER,
            x_labels=PUSHBACK_LABELS,
            y_column="flip_rate",
            low_column="ci_low",
            high_column="ci_high",
            y_label="Flip rate after pushback",
            title="Set 4: pushback by address form and teacher claim (Set 3)",
            figsize=size,
        )
        save_figure_pair(fig, figures / "p_pushback_forms")
        plt.close(fig)
    print(f"Saved figures to {figures}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
