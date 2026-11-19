"""Refit only the sigmoid calibrator of the 2021 forecaster on recent live data.

The LightGBM trees are unchanged. The live replay from validate_live_2026.py is
split chronologically by Chicago service day: the first --fit-days days fit one
Platt sigmoid per target on the raw LightGBM output (as in training), the
remaining days are held out. Fit rows whose 60-minute horizon would reach the
held-out period are dropped. The held-out comparison (2021 calibrator vs. 2026
calibrator vs. B1) decides whether the new calibrator is worth serving; if
--write-artifact is given and it is better on held-out Brier and ECE for both
targets, the parameters are written for the app's Live mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'scripts/model')]

from backend.artifacts import resolve_data_root  # noqa: E402
from backend.providers import ZONE  # noqa: E402
from bikeflow_model.baselines import b1_persistence  # noqa: E402
from bikeflow_model.forecaster import ForecasterService, Sigmoid, predict_target  # noqa: E402
from bikeflow_model.metrics import day_block_bootstrap, reliability_table, summary  # noqa: E402
from validate_live_2026 import MAX_AGE, TARGETS, build_rows, load_polls  # noqa: E402
from backend.core import registry  # noqa: E402

GAP = 3600  # longest horizon


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--live-root', type=Path, required=True)
    p.add_argument('--data-root', type=Path)
    p.add_argument('--fit-days', type=int, default=10)
    p.add_argument('--cache', type=Path, default=PROJECT / '.local/live_validation/app32_polls.parquet')
    p.add_argument('--out', type=Path, default=PROJECT / 'reports/live_validation_2026/recalibration')
    p.add_argument('--write-artifact', type=Path, help='e.g. artifacts/live_calibration.json')
    a = p.parse_args()
    root, _ = resolve_data_root(a.data_root)
    df = build_rows(load_polls(a.live_root, registry(), a.cache))
    days = sorted(df.service_day.unique())
    fit_days, eval_days = days[:a.fit_days], days[a.fit_days:]
    boundary = pd.Timestamp(eval_days[0], tz=ZONE).timestamp()
    fit = df[df.service_day.isin(fit_days) & (df.request_time + GAP <= boundary)]
    held = df[df.service_day.isin(eval_days)]
    service = ForecasterService(root / 'models/forecaster_v0_m3', None, max_input_age_seconds=MAX_AGE)
    rows, boot, rel, params = [], [], {}, {}
    for target in TARGETS:
        model = service.models[target]
        raw_fit = predict_target(model, fit, service.columns, service.categories, calibrated=False)
        new = Sigmoid.fit(raw_fit, fit[f'{target}_unavailable'].to_numpy(int))
        params[target] = dict(a=new.a, b=new.b, original=dict(a=model.calibrator.a, b=model.calibrator.b))
        raw = predict_target(model, held, service.columns, service.categories, calibrated=False)
        y = held[f'{target}_unavailable'].to_numpy(float)
        methods = {'B1': b1_persistence(held, target), 'LGBM_2021_calibration': model.calibrator(raw),
                   'LGBM_2026_calibration': new(raw)}
        for h in ['all', 10, 30, 60]:
            m = np.ones(len(held), bool) if h == 'all' else (held.horizon_minutes == h).to_numpy()
            for name, pr in methods.items():
                rows.append(dict(target=target, horizon=h, method=name, **summary(pr[m], y[m])))
            b = day_block_bootstrap(methods['LGBM_2026_calibration'][m], methods['LGBM_2021_calibration'][m], y[m],
                                    held.service_day.to_numpy()[m], n_boot=2000)
            boot.append(dict(target=target, horizon=h, comparison='2026 calibration - 2021 calibration', **b))
        m30 = (held.horizon_minutes == 30).to_numpy()
        rel[target] = {k: reliability_table(v[m30], y[m30]) for k, v in methods.items() if k != 'B1'}
    metrics, boot = pd.DataFrame(rows), pd.DataFrame(boot)
    a.out.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(a.out / 'heldout_metrics.csv', index=False)
    boot.to_csv(a.out / 'heldout_bootstrap.csv', index=False)
    allh = metrics[metrics.horizon == 'all'].set_index(['target', 'method'])
    better = all(allh.loc[(t, 'LGBM_2026_calibration'), k] < allh.loc[(t, 'LGBM_2021_calibration'), k]
                 for t in TARGETS for k in ('brier', 'ece'))
    result = dict(model_version=service.version, fit_days=list(fit_days), heldout_days=list(eval_days),
                  fit_rows=int(len(fit)), heldout_rows=int(len(held)), separation_seconds=GAP,
                  calibrators=params, heldout_better_on_brier_and_ece=bool(better), reliability_30min=rel)
    (a.out / 'summary.json').write_text(json.dumps(result, indent=2, default=float) + '\n', encoding='utf-8')
    if a.write_artifact and better:
        a.write_artifact.write_text(json.dumps(dict(
            purpose='Live-mode sigmoid calibrators for the unchanged 2021 LightGBM trees, refit on 2026 live data',
            model_version=service.version,
            fitted_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
            fit_service_days=[fit_days[0], fit_days[-1]], heldout_service_days=[eval_days[0], eval_days[-1]],
            fit_rows=int(len(fit)),
            calibrators={t: dict(a=params[t]['a'], b=params[t]['b']) for t in TARGETS},
            report='reports/live_validation_2026/recalibration/README.md'), indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'reliability_30min'}, indent=2, default=float))
    print(metrics[metrics.horizon == 'all'].round(4).to_string(index=False))
    print(boot.round(4).to_string(index=False))


if __name__ == '__main__':
    main()
