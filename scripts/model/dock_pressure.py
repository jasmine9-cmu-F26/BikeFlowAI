"""Dock-side results where docks are actually scarce.

Network averages hide the dock forecast: open docks are missing only 2-3% of
the time. This scores the dock target on subsets chosen from decision-time
information only (never from outcomes):

* nearly_full_now:   <= 2 open docks in the base observation;
* busy_dock_hour:    the training-period (B2) dock-unavailable rate for the
                     station at the target hour is >= 10%.

Part A scores B1 / B2 / LightGBM on the 2021 tune rows (from the repo's demo
bundle) and, with --live-root, on the 2026 live replay. Part B reads replay
episodes from evaluate.py (--episodes) and compares full-dock arrivals
(failed return attempts; the rider rides on to a backup) for riders whose
destination is in a busy dock hour at checkout. Outputs go to
reports/dock_pressure/.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'scripts/model'), str(PROJECT / 'scripts/rl')]

from backend.artifacts import resolve_data_root  # noqa: E402
from backend.providers import ZONE  # noqa: E402
from bikeflow_model.baselines import b1_persistence, b2_historical  # noqa: E402
from bikeflow_model.data import add_derived  # noqa: E402
from bikeflow_model.forecaster import ForecasterService  # noqa: E402
from bikeflow_model.metrics import day_block_bootstrap, summary  # noqa: E402

BUSY = 0.10
NEARLY_FULL = 2


def tune_rows(root: Path) -> pd.DataFrame:
    table = root / 'processed/final_pipeline_v1'
    feats = pd.concat(pd.read_parquet(p) for p in sorted(glob.glob(str(table / 'features/*_tune.parquet'))))
    labels = pd.concat(pd.read_parquet(p, columns=['row_id', 'dock_unavailable'])
                       for p in sorted(glob.glob(str(table / 'labels/*_tune.parquet'))))
    df = add_derived(feats.merge(labels, on='row_id', validate='one_to_one'))
    return df[df.base_age_seconds <= 900].reset_index(drop=True)


def score(df: pd.DataFrame, service: ForecasterService, rates: pd.DataFrame, label: str):
    y = df['dock_unavailable'].to_numpy(float)
    p = {'B1': b1_persistence(df, 'dock'), 'B2': b2_historical(df, rates, 'dock'),
         'LGBM': 1.0 - service.predict(df)['p_dock_available'].to_numpy(float)}
    ok = np.all([~np.isnan(v) for v in p.values()], axis=0)
    subsets = {'all': np.ones(len(df), bool),
               'nearly_full_now': (df.num_docks_available <= NEARLY_FULL).to_numpy(),
               'busy_dock_hour': p['B2'] >= BUSY}
    subsets['either'] = subsets['nearly_full_now'] | subsets['busy_dock_hour']
    rows = []
    for name, mask in subsets.items():
        m = ok & mask
        out = dict(data=label, subset=name, share_of_rows=float(m.sum() / ok.sum()))
        for method, v in p.items():
            s = summary(v[m], y[m])
            out.update(n=s['n'], base_rate=s['base_rate'], **{f'{method}_{k}': s[k] for k in ('brier', 'pr_auc', 'ece')})
        ref = min(('B1', 'B2'), key=lambda k: out[f'{k}_brier'])
        b = day_block_bootstrap(p['LGBM'][m], p[ref][m], y[m], df.service_day.to_numpy()[m], n_boot=2000)
        out.update(best_baseline=ref, lgbm_vs_best_relative=b['relative_change'], ci95=b['relative_change_ci95'])
        rows.append(out)
    return rows


def episodes_table(paths, rates: pd.DataFrame):
    """Return failures for riders whose destination is in a busy dock hour at checkout."""
    from evaluate import day_bootstrap
    b2 = rates.set_index(['station_id', 'weekday', 'hour'])['dock_available_rate']
    out = []
    for path in paths:
        e = pd.read_csv(path)
        cell = Path(path).parent.name
        t = pd.to_datetime(e.checkout, unit='s', utc=True).dt.tz_convert(ZONE)
        keys = list(zip(e.dest, t.dt.dayofweek, t.dt.hour))
        e['dest_dock_risk'] = 1.0 - b2.reindex(keys).to_numpy()
        e = e[e.outcome.isin(['success', 'failure'])].copy()
        e['return_failure'] = ((e.outcome == 'failure') & (e.phase == 'return')).astype(float)
        e['policy'] = e.policy.str.replace(r'_seed\d+$', '', regex=True)
        for subset, m in (('all', np.ones(len(e), bool)), ('busy_dock_destination', (e.dest_dock_risk >= BUSY).to_numpy())):
            sub = e[m]
            row = dict(cell=cell, subset=subset, requests=int(sub.request.nunique()))
            for pol, g in sub.groupby('policy'):
                row[f'{pol}_trip_failure'] = float((g.outcome == 'failure').mean())
                row[f'{pol}_return_failure'] = float(g.return_failure.mean())
                if 'return_failures' in g:
                    row[f'{pol}_full_dock_arrivals'] = float(g.return_failures.mean())
            b1 = sub[sub.policy == 'B1'].set_index('request')
            metric = 'return_failures' if 'return_failures' in sub else 'return_failure'
            for pol in ('B2', 'B3', 'RL'):
                g = sub[sub.policy == pol].groupby('request')[metric].mean()  # RL: mean of seeds
                common = g.index.intersection(b1.index)
                if len(common):
                    d, lo, hi = day_bootstrap(g.loc[common].to_numpy(), b1.loc[common, metric].to_numpy(),
                                              b1.loc[common, 'day'].to_numpy())
                    row[f'{pol}_minus_B1_{metric}'] = d
                    row[f'{pol}_minus_B1_ci95'] = [lo, hi]
            out.append(row)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data-root', type=Path, help='serving package (default: bundled demo data)')
    p.add_argument('--live-root', type=Path, help='collector current_validation/ for the 2026 rows')
    p.add_argument('--episodes', type=Path, nargs='*', default=[], help='evaluate.py episodes.csv files')
    p.add_argument('--out', type=Path, default=PROJECT / 'reports/dock_pressure')
    a = p.parse_args()
    root, _ = resolve_data_root(a.data_root)
    rates = pd.read_parquet(root / 'processed/final_pipeline_v1/B2/heldout_training_fit_rates.parquet')
    service = ForecasterService(root / 'models/forecaster_v0_m3', rates)
    rows = score(tune_rows(root), service, rates, '2021 tune')
    if a.live_root:
        from validate_live_2026 import build_rows, load_polls
        from backend.core import registry
        live = build_rows(load_polls(a.live_root, registry(), PROJECT / '.local/live_validation/app32_polls.parquet'))
        rows += score(live, service, rates, '2026 live')
    a.out.mkdir(parents=True, exist_ok=True)
    forecast = pd.DataFrame(rows)
    forecast.to_csv(a.out / 'dock_forecast_subsets.csv', index=False)
    result = dict(forecast=rows)
    if a.episodes:
        planner = episodes_table(a.episodes, rates)
        pd.DataFrame(planner).to_csv(a.out / 'planner_return_failures.csv', index=False)
        result['planner'] = planner
    (a.out / 'summary.json').write_text(json.dumps(result, indent=2, default=float) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=1, default=float))


if __name__ == '__main__':
    main()
