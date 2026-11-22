"""Intervals, tests and agreement used in the analysis.

Formula (write-up, Methods)::

    flip_rate     = gave_in / (gave_in + kept)
    accuracy_drop = acc_plain - acc_wrong_guess
    McNemar p     = min(1, 2 * sum_{k=0}^{min(b, c)} C(b + c, k) / 2^(b + c))
    kappa         = (p_o - p_e) / (1 - p_e)

``b`` and ``c`` are the two kinds of disagreement in a paired comparison (right
in A and wrong in B, and the reverse). ``p_o`` is observed agreement and ``p_e``
the agreement expected by chance from each rater's label shares.

Intervals
---------
95% intervals are percentile bootstrap intervals with 2,000 resamples and a
fixed seed, so the tables can be reproduced exactly. Paired comparisons (the
same questions in both cells, such as Set 1 against Set 2) resample the
per-question differences. Unpaired comparisons (different questions, such as
Western against Bangladesh content) resample each group on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import comb

import numpy as np

from bengali_sycophancy.constants import BOOTSTRAP_RESAMPLES, RNG_SEED


def bootstrap_mean_ci(
    values: np.ndarray,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = RNG_SEED,
) -> tuple[float, float]:
    """95% percentile interval for the mean of ``values`` (1-D, float)."""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, values.size, size=(resamples, values.size))
    means = values[idx].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return (float(low), float(high))


def bootstrap_diff_ci(
    a: np.ndarray,
    b: np.ndarray,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = RNG_SEED,
) -> tuple[float, float]:
    """95% interval for ``mean(a) - mean(b)`` when a and b are different questions."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    mean_a = a[rng.integers(0, a.size, size=(resamples, a.size))].mean(axis=1)
    mean_b = b[rng.integers(0, b.size, size=(resamples, b.size))].mean(axis=1)
    low, high = np.percentile(mean_a - mean_b, [2.5, 97.5])
    return (float(low), float(high))


def mcnemar_exact_p(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from the two disagreement counts."""
    if b < 0 or c < 0:
        raise ValueError(f"counts must be non-negative, got b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**n)


def cohen_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float:
    """Cohen's kappa for two raters labelling the same items."""
    if len(rater_a) != len(rater_b):
        raise ValueError("both raters must label the same number of items")
    if not rater_a:
        raise ValueError("no items to compare")
    n = len(rater_a)
    labels = set(rater_a) | set(rater_b)
    observed = sum(x == y for x, y in zip(rater_a, rater_b)) / n
    expected = sum(
        (list(rater_a).count(lab) / n) * (list(rater_b).count(lab) / n)
        for lab in labels
    )
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)
