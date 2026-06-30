"""A from-scratch species-distribution model.

We fit a used-vs-available logistic regression: cells where the species was
observed are "used" (y=1); the whole grid is "available" background (y=0). In
the limit of heavy background weighting this is an inhomogeneous Poisson point
process — the same model MaxEnt fits (Renner & Warton 2013) — so this is a
legitimate SDM, just written transparently in numpy instead of a black box.

Features are standardized and given quadratic terms, which lets the model
express a unimodal niche (a species prefers a middle band of elevation /
temperature, not "more is always better"). L2 regularization on the non-
intercept weights is the analogue of MaxEnt's regularization: it keeps the
fitted niche from chasing noise in a small presence sample.

We predict only on the grid the model was trained over, so there is no
environmental extrapolation. Output is a per-cell suitability in [0, 1] plus a
background AUC as an honest, if optimistic, discrimination score.
"""

from __future__ import annotations

import numpy as np

FEATURES = ("elevation", "temp", "tempSeasonality", "precip")
MIN_PRESENCE_CELLS = 5


def _standardize_stats(cells: list[dict], keys) -> tuple[dict, dict]:
    means = {k: float(np.mean([c[k] for c in cells])) for k in keys}
    stds = {k: float(np.std([c[k] for c in cells])) or 1.0 for k in keys}
    return means, stds


def _design_matrix(cells: list[dict], keys, means, stds) -> np.ndarray:
    """Standardized linear + quadratic features (no intercept column)."""
    rows = []
    for c in cells:
        z = [(c[k] - means[k]) / stds[k] for k in keys]
        rows.append(z + [v * v for v in z])
    return np.asarray(rows, dtype=float)


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann–Whitney AUC: P(score(presence) > score(background))."""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort() + 1
    r_pos = ranks[: len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def fit_predict(
    cells: list[dict],
    presence_idx: list[int],
    keys=FEATURES,
    l2: float = 1.0,
    lr: float = 0.2,
    epochs: int = 4000,
) -> dict | None:
    """
    Fit the used-vs-available logistic model and predict suitability per cell.

    Returns None if there are too few presence cells to fit responsibly.
    """
    if len(presence_idx) < MIN_PRESENCE_CELLS:
        return None

    means, stds = _standardize_stats(cells, keys)
    X = _design_matrix(cells, keys, means, stds)
    n = X.shape[0]

    # Training set: presences (y=1) + all cells as background (y=0).
    Xp = X[presence_idx]
    X_train = np.vstack([Xp, X])
    y_train = np.concatenate([np.ones(len(presence_idx)), np.zeros(n)])

    # Balance presence vs background so the rarer class isn't drowned out.
    w = np.concatenate([
        np.ones(len(presence_idx)),
        np.full(n, len(presence_idx) / n),
    ])

    # Prepend intercept column.
    X_train = np.hstack([np.ones((X_train.shape[0], 1)), X_train])
    beta = np.zeros(X_train.shape[1])
    w_sum = w.sum()

    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-(X_train @ beta)))
        grad = X_train.T @ (w * (p - y_train)) / w_sum
        grad[1:] += l2 * beta[1:] / w_sum  # L2 on non-intercept weights
        beta -= lr * grad

    X_all = np.hstack([np.ones((n, 1)), X])
    suitability = 1.0 / (1.0 + np.exp(-(X_all @ beta)))

    presence_mask = np.zeros(n, dtype=bool)
    presence_mask[presence_idx] = True
    auc = _auc(suitability[presence_mask], suitability[~presence_mask])

    # Report standardized linear weights for interpretability.
    weights = {k: round(float(beta[1 + i]), 3) for i, k in enumerate(keys)}

    return {
        "suitability": [round(float(s), 4) for s in suitability],
        "auc": round(auc, 3) if auc == auc else None,
        "weights": weights,
        "presenceCells": len(presence_idx),
    }
