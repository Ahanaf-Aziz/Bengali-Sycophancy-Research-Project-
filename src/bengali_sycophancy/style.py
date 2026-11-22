"""One look for every figure.

Call ``apply_style()`` once at the top of a plotting script. Plot code takes
colours from ``PALETTE`` and never hard-codes a hex value.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 - backend must be set first

# Colour-blind-safe palette.
# Source: Okabe and Ito (2008), "Color Universal Design".
PALETTE = {
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "black": "#000000",
    "grey": "#999999",
}

# Fixed colour per tested model, so a model looks the same in every figure.
MODEL_COLOURS = {
    "claude": PALETTE["vermillion"],
    "gpt": PALETTE["blue"],
    "qwen-7b": PALETTE["green"],
    "tiny-aya": PALETTE["purple"],
}
FALLBACK_COLOURS = (PALETTE["orange"], PALETTE["sky_blue"], PALETTE["black"])

# Figure widths in inches. LessWrong has no column template, so these follow a
# common two-column paper layout, which also reads well on screen.
SINGLE_COLUMN_IN = 3.5
DOUBLE_COLUMN_IN = 7.0

SERIF_FALLBACK = ("Times New Roman", "Nimbus Roman", "DejaVu Serif")


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": list(SERIF_FALLBACK),
            "font.size": 9,
            "axes.titlesize": 9,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": PALETTE["grey"],
            "grid.alpha": 0.3,
            "text.usetex": False,
        }
    )


def model_colour(model: str, index: int) -> str:
    return MODEL_COLOURS.get(model, FALLBACK_COLOURS[index % len(FALLBACK_COLOURS)])


def save_figure(fig: plt.Figure, path: Path) -> None:
    """Vector PDF at 300 dpi with a tight bounding box."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".pdf"), dpi=300, bbox_inches="tight")


def save_figure_pair(fig: plt.Figure, stem: Path) -> None:
    """The publication PDF plus a PNG for review and for the post."""
    save_figure(fig, stem)
    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
