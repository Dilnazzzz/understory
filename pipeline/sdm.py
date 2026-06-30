"""A from-scratch species-distribution model with spatial bias correction.

We fit a used-vs-available logistic regression: cells where the species was
observed are "used" (y=1); the grid is "available" background (y=0). In the
heavy-background limit this is an inhomogeneous Poisson point process — the
model MaxEnt fits (Renner & Warton 2013) — so it is a legitimate SDM, written
transparently in numpy.

Two corrections turn the toy into something defensible:

  Target-group background (TGB). Presence-only data is spatially biased: records
  cluster where people look (near trails, towns, active observers). A naive
  model learns that bias, not the niche. TGB draws the background in proportion
  to the survey effort of the whole target group (all our species' records), so
  presence and background share the same bias and it cancels. Background weight
  per cell ∝ total target-group observations there; never-surveyed cells get no
  background weight (we only compare against places someone actually checked).

  Spatial block cross-validation. Nearby cells are correlated (Tobler's law), so
  a random train/test split leaks and inflates AUC. We partition the region into
  spatial blocks, assign them to folds so held-out data is geographically
  separated, and report the pooled out-of-fold AUC — an honest score, usually
  lower than the optimistic in-sample background AUC.

Features are standardized with quadratic terms (unimodal niches); L2 on the
non-intercept weights is the analogue of MaxEnt's regularization.
"""

from __future__ import annotations

import math

import numpy as np

FEATURES = ("elevation", "temp", "tempSeasonality", "precip")
MIN_PRESENCE_CELLS = 5
CV_BLOCK_DEG = 0.3
CV_FOLDS = 4


def _standardize_stats(cells, keys):
    means = {k: float(np.mean([c[k] for c in cells])) for k in keys}
    stds = {k: float(np.std([c[k] for c in cells])) or 1.0 for k in keys}
    return means, stds


def _design_matrix(cells, keys, means, stds) -> np.ndarray:
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


def _fit(X: np.ndarray, presence_idx, effort: np.ndarray, l2, lr, epochs) -> np.ndarray:
    """Fit weights via gradient descent with target-group-weighted background."""
    n = X.shape[0]

    eff_total = effort.sum()
    if eff_total <= 0:
        bg_w = np.full(n, len(presence_idx) / n)
    else:
        # Background weight ∝ survey effort; total background weight == #presence.
        bg_w = effort / eff_total * len(presence_idx)

    Xp = X[presence_idx]
    X_train = np.vstack([Xp, X])
    y_train = np.concatenate([np.ones(len(presence_idx)), np.zeros(n)])
    w = np.concatenate([np.ones(len(presence_idx)), bg_w])

    X_train = np.hstack([np.ones((X_train.shape[0], 1)), X_train])
    beta = np.zeros(X_train.shape[1])
    w_sum = w.sum()

    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-(X_train @ beta)))
        grad = X_train.T @ (w * (p - y_train)) / w_sum
        grad[1:] += l2 * beta[1:] / w_sum
        beta -= lr * grad
    return beta


def _predict(X: np.ndarray, beta: np.ndarray) -> np.ndarray:
    X1 = np.hstack([np.ones((X.shape[0], 1)), X])
    return 1.0 / (1.0 + np.exp(-(X1 @ beta)))


def _fold_of(cell: dict, block_deg: float, k: int) -> int:
    """Assign a cell to a spatial fold via its block coordinates (checkerboard)."""
    bi = math.floor(cell["lat"] / block_deg)
    bj = math.floor(cell["lng"] / block_deg)
    return (bi + bj) % k


def _spatial_cv_auc(cells, X, presence_idx, effort, l2, lr, epochs) -> float | None:
    """Pooled out-of-fold AUC from spatial block cross-validation."""
    n = len(cells)
    folds = np.array([_fold_of(c, CV_BLOCK_DEG, CV_FOLDS) for c in cells])
    presence_mask = np.zeros(n, dtype=bool)
    presence_mask[presence_idx] = True

    oof_scores: list[float] = []
    oof_labels: list[int] = []

    for f in range(CV_FOLDS):
        train_mask = folds != f
        test_mask = folds == f

        train_presence = [i for i in presence_idx if train_mask[i]]
        if len(train_presence) < MIN_PRESENCE_CELLS:
            continue

        train_global = np.where(train_mask)[0]
        g2l = {g: l for l, g in enumerate(train_global)}
        local_presence = [g2l[i] for i in train_presence]

        beta = _fit(X[train_mask], local_presence, effort[train_mask], l2, lr, epochs)
        test_scores = _predict(X[test_mask], beta)

        for local_i, global_i in enumerate(np.where(test_mask)[0]):
            if presence_mask[global_i]:
                oof_scores.append(test_scores[local_i])
                oof_labels.append(1)
            elif effort[global_i] > 0:  # surveyed, species not found = true negative
                oof_scores.append(test_scores[local_i])
                oof_labels.append(0)

    labels = np.array(oof_labels)
    scores = np.array(oof_scores)
    if labels.sum() == 0 or labels.sum() == len(labels):
        return None
    return round(_auc(scores[labels == 1], scores[labels == 0]), 3)


def fit_predict(
    cells: list[dict],
    presence_idx: list[int],
    effort: list[float],
    keys=FEATURES,
    l2: float = 1.0,
    lr: float = 0.2,
    epochs: int = 4000,
) -> dict | None:
    """Fit the bias-corrected model and predict suitability per cell."""
    if len(presence_idx) < MIN_PRESENCE_CELLS:
        return None

    means, stds = _standardize_stats(cells, keys)
    X = _design_matrix(cells, keys, means, stds)
    effort_arr = np.asarray(effort, dtype=float)

    beta = _fit(X, presence_idx, effort_arr, l2, lr, epochs)
    suitability = _predict(X, beta)

    presence_mask = np.zeros(len(cells), dtype=bool)
    presence_mask[presence_idx] = True
    bg_auc = _auc(suitability[presence_mask], suitability[~presence_mask])
    spatial_auc = _spatial_cv_auc(cells, X, presence_idx, effort_arr, l2, lr, epochs)

    weights = {k: round(float(beta[1 + i]), 3) for i, k in enumerate(keys)}

    return {
        "suitability": [round(float(s), 4) for s in suitability],
        "auc": round(bg_auc, 3) if bg_auc == bg_auc else None,
        "spatialAuc": spatial_auc,
        "weights": weights,
        "presenceCells": len(presence_idx),
    }
