"""Forward-chaining (expanding-week) forecaster probabilities for the TRAIN pool.

The RL policy trains on train-split requests, so it needs forecaster
probabilities that were never fit on the week being predicted. For week k
(k >= 2): fit on targets before week k-1, early-stop + sigmoid-calibrate on
week k-1, predict week k. Weeks 0-1 have no forward model (cold start; the
planner falls back to B2/B1 there). Only the train split is read.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bikeflow_model import LABEL_COLUMN, TARGETS  # noqa: E402
from bikeflow_model import baselines, metrics  # noqa: E402
from bikeflow_model.data import PROJECT, feature_columns, load_schema, load_split  # noqa: E402
from bikeflow_model.forecaster import fit_target, predict_target  # noqa: E402
from train_forecaster import train_bounds  # noqa: E402

WEEK = 7 * 86400


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--out', type=Path, default=None, help='default: <data-root>/models/forecaster_v0_m3/forward_train_predictions.parquet')
    p.add_argument('--reports', type=Path, default=PROJECT / 'reports/forecaster_m3')
    p.add_argument('--first-week', type=int, default=2)
    args = p.parse_args()
    t0 = time.time()
    columns = feature_columns(load_schema())
    train = load_split(args.data_root, ['train'], load_schema())
    lo, hi = train_bounds()
    categories = sorted(train['station_id'].unique())
    n_weeks = int(round((hi - lo) / WEEK))
    parts, report = [], []
    for k in range(args.first_week, n_weeks):
        prev, cur, nxt = lo + (k - 1) * WEEK, lo + k * WEEK, min(hi, lo + (k + 1) * WEEK)
        fit_df = train[train['target_time'] < prev]
        cal_df = train[(train['request_time'] >= prev) & (train['target_time'] < cur)]
        pred_df = train[(train['request_time'] >= cur) & (train['request_time'] < nxt)]
        out = pred_df[['row_id', 'station_id', 'request_time', 'horizon_minutes']].copy()
        out['fold_week'] = k
        for target in TARGETS:
            model = fit_target(fit_df, cal_df, target, columns, categories)
            prob = predict_target(model, pred_df, columns, categories)
            out[f'p_{target}_unavailable'] = prob
            y = pred_df[LABEL_COLUMN[target]].to_numpy()
            report.append(dict(fold_week=k, target=target, fit_rows=len(fit_df), calibration_rows=len(cal_df), predicted_rows=len(pred_df),
                               best_iteration=model.best_iteration, brier=metrics.brier(prob, y), ece=metrics.ece(prob, y),
                               brier_B1=metrics.brier(baselines.b1_persistence(pred_df, target), y)))
            print(f'week {k} {target}: brier={report[-1]["brier"]:.5f} B1={report[-1]["brier_B1"]:.5f} ({time.time()-t0:.0f}s)', flush=True)
        parts.append(out)
    dest = args.out or args.data_root / 'models/forecaster_v0_m3/forward_train_predictions.parquet'
    dest.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(parts).to_parquet(dest, index=False)
    args.reports.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report).to_csv(args.reports / 'forward_chaining_folds.csv', index=False)
    covered = int(sum(len(x) for x in parts))
    (args.reports / 'forward_chaining_summary.json').write_text(json.dumps(dict(
        status='train_pool_forward_probabilities_for_policy_training', folds=len(parts), first_week=args.first_week,
        rows_with_forward_probabilities=covered, train_rows=len(train), coverage=covered / len(train),
        cold_start='weeks before first_week have no forward model; planner uses B2/B1 there',
        output=str(dest), runtime_seconds=round(time.time() - t0, 1)), indent=2) + '\n', encoding='utf-8')
    print(f'wrote {covered:,} rows -> {dest}')


if __name__ == '__main__':
    main()
