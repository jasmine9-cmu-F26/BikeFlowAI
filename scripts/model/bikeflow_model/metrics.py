"""Probability metrics and paired day-block bootstrap."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

EPS = 1e-6


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y) -> float:
    p, y = np.clip(np.asarray(p, float), EPS, 1 - EPS), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(p, y, bins: int = 10) -> float:
    """Expected calibration error with fixed equal-width bins (probability units, not %)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    ix = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = ix == b
        if m.any():
            total += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(total / len(p))


def reliability_table(p, y, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    ix = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = ix == b
        rows.append(dict(bin=b, lo=float(edges[b]), hi=float(edges[b + 1]), n=int(m.sum()),
                         mean_pred=float(p[m].mean()) if m.any() else None,
                         observed_rate=float(y[m].mean()) if m.any() else None))
    return rows


def pr_auc(p, y) -> float | None:
    y = np.asarray(y)
    return float(average_precision_score(y, p)) if 0 < y.sum() < len(y) else None


def roc_auc(p, y) -> float | None:
    y = np.asarray(y)
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None


def summary(p, y) -> dict:
    y = np.asarray(y)
    return dict(n=int(len(y)), positives=int(y.sum()), base_rate=float(y.mean()), brier=brier(p, y),
                log_loss=log_loss(p, y), ece=ece(p, y), pr_auc=pr_auc(p, y), roc_auc=roc_auc(p, y))


def day_block_bootstrap(model_p, ref_p, y, days, n_boot: int = 2000, seed: int = 668) -> dict:
    """Paired bootstrap over whole service days of the Brier difference (model - reference).

    Rows within a day (stations x times x horizons) are strongly dependent, so
    days, not rows, are resampled. Negative values mean the model is better.
    """
    model_p, ref_p, y = (np.asarray(a, float) for a in (model_p, ref_p, y))
    days = np.asarray(days)
    labels, inverse = np.unique(days, return_inverse=True)
    k = len(labels)
    se_m = np.bincount(inverse, (model_p - y) ** 2, minlength=k)
    se_r = np.bincount(inverse, (ref_p - y) ** 2, minlength=k)
    cnt = np.bincount(inverse, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, k, size=(n_boot, k))
    w = np.stack([np.bincount(d, minlength=k) for d in draws])
    bm, br = (w @ se_m) / (w @ cnt), (w @ se_r) / (w @ cnt)
    diff, rel = bm - br, (bm - br) / br
    point_m, point_r = se_m.sum() / cnt.sum(), se_r.sum() / cnt.sum()
    return dict(days=int(k), n_boot=n_boot, seed=seed,
                brier_diff=float(point_m - point_r),
                brier_diff_ci95=[float(np.quantile(diff, 0.025)), float(np.quantile(diff, 0.975))],
                relative_change=float((point_m - point_r) / point_r),
                relative_change_ci95=[float(np.quantile(rel, 0.025)), float(np.quantile(rel, 0.975))],
                p_model_not_better=float(np.mean(diff >= 0)))
