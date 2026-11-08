"""Milestone 3: train the LightGBM forecaster and compare it with B1/B2 on the TUNE split.

Protocol (no calibration/test data is read):
  * fit:        train rows whose target time is before (train_end - 14 days)
  * inner:      last 14 days of train -> early stopping + provisional sigmoid calibration
  * report:     tune split (2 weeks) -> Brier / log loss / ECE / PR-AUC per horizon,
                paired day-block bootstrap vs the better of B1 and B2.
The frozen calibration split is reserved for the final calibrator and test for final reporting.
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
from bikeflow_model.data import PROJECT, SCHEMA_PATH, feature_columns, load_schema, load_split, pipeline_root  # noqa: E402
from bikeflow_model.forecaster import fit_target, predict_target, save_bundle, sha256  # noqa: E402

INNER_DAYS = 14
BASELINES = ('B1', 'B1cal', 'B2')
LAG_COLUMNS_PREFIX = ('bike_delta_', 'dock_delta_', 'lag_')
METHOD_LABEL = {'B1': 'B1 persistence', 'B1cal': 'B1-cal calibrated persistence', 'B2': 'B2 historical rate', 'LGBM_raw': 'LightGBM (uncalibrated)', 'LGBM': 'LightGBM + sigmoid'}


def _names():
    import csv
    with (PROJECT / 'data/manifests/chicago/app_stations.csv').open(encoding='utf-8', newline='') as f:
        return {r['station_id']: r['historical_name'] for r in csv.DictReader(f)}


NAMES = _names()


def train_bounds():
    protocol = json.loads((PROJECT / 'data/manifests/chicago/app32/data_protocol.json').read_text(encoding='utf-8'))
    s = next(s for s in protocol['chronological_splits'] if s['split'] == 'train')
    to_epoch = lambda v: int(pd.Timestamp(v).timestamp())  # noqa: E731
    return to_epoch(s['start_utc']), to_epoch(s['end_utc_exclusive'])


def evaluate(df, preds, target):
    """Per-horizon and overall metrics for every method; best baseline picked on tune Brier."""
    y = df[LABEL_COLUMN[target]].to_numpy()
    rows, boots = [], []
    groups = [('all', np.ones(len(df), bool))] + [(int(h), (df['horizon_minutes'] == h).to_numpy()) for h in sorted(df['horizon_minutes'].unique())]
    for h, m in groups:
        stats = {k: metrics.summary(v[m], y[m]) for k, v in preds.items()}
        for k, s in stats.items():
            rows.append(dict(target=target, horizon=h, method=k, **s))
        # 'proposal': goal as written in Milestone 2 (better of B1/B2); 'strong': adds calibrated persistence.
        for comparison, pool in (('proposal_B1_B2', ('B1', 'B2')), ('strong_incl_B1cal', BASELINES)):
            best = min(pool, key=lambda k: stats[k]['brier'])
            b = metrics.day_block_bootstrap(preds['LGBM'][m], preds[best][m], y[m], df['service_day'].to_numpy()[m])
            boots.append(dict(target=target, horizon=h, comparison=comparison, reference=best, reference_brier=stats[best]['brier'],
                              model_brier=stats['LGBM']['brier'], **b,
                              meets_10pct_goal=b['relative_change'] <= -0.10, meets_ece_goal=stats['LGBM']['ece'] <= 0.05))
    return rows, boots


def slice_metrics(df, preds, target):
    y = df[LABEL_COLUMN[target]].to_numpy()
    weekday = df['weekday'].to_numpy() < 5
    hour = df['hour'].to_numpy()
    peak = weekday & (((hour >= 7) & (hour < 10)) | ((hour >= 16) & (hour < 19)))
    out = []
    for name, m in [('weekday_peak', peak), ('weekday_offpeak', weekday & ~peak), ('weekend', ~weekday)]:
        for k in BASELINES + ('LGBM',):
            out.append(dict(target=target, slice=name, method=k, **metrics.summary(preds[k][m], y[m])))
    return out


def station_metrics(df, preds, target, horizon=30):
    m = (df['horizon_minutes'] == horizon).to_numpy()
    sub = df.loc[m, ['station_id', LABEL_COLUMN[target]]].copy()
    for k in BASELINES + ('LGBM',):
        sub[k] = (preds[k][m] - sub[LABEL_COLUMN[target]].to_numpy()) ** 2
    g = sub.groupby('station_id').agg(n=(LABEL_COLUMN[target], 'size'), unavailable_rate=(LABEL_COLUMN[target], 'mean'),
                                       brier_B1=('B1', 'mean'), brier_B1cal=('B1cal', 'mean'), brier_B2=('B2', 'mean'), brier_LGBM=('LGBM', 'mean')).reset_index()
    g['target'], g['horizon'] = target, horizon
    g['lgbm_minus_best_baseline'] = g['brier_LGBM'] - g[['brier_B1', 'brier_B1cal', 'brier_B2']].min(axis=1)
    return g.sort_values('lgbm_minus_best_baseline')


def pick_examples(df, preds, target, horizon=30):
    """Station-day with the largest LightGBM gain over B1 (success) and the largest loss (failure)."""
    m = (df['horizon_minutes'] == horizon).to_numpy()
    sub = df.loc[m, ['station_id', 'service_day', LABEL_COLUMN[target]]].copy()
    y = sub[LABEL_COLUMN[target]].to_numpy()
    sub['gain'] = (preds['B1'][m] - y) ** 2 - (preds['LGBM'][m] - y) ** 2
    g = sub.groupby(['station_id', 'service_day']).agg(gain=('gain', 'sum'), events=(LABEL_COLUMN[target], 'sum'), n=('gain', 'size'))
    mixed = g[(g['events'] >= 3) & (g['events'] <= g['n'] - 3)]
    g = mixed if len(mixed) else g
    return g['gain'].idxmax(), g['gain'].idxmin()


def plot_all(out, df, results, preds_by_target, importance, examples):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig_dir = out / 'figures'
    fig_dir.mkdir(parents=True, exist_ok=True)
    colors = {'B1': '#9a9a9a', 'B1cal': '#5b9a68', 'B2': '#d08c2c', 'LGBM_raw': '#8fb3d9', 'LGBM': '#1f5fa8'}
    res = pd.DataFrame(results)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, target in zip(axes, TARGETS):
        r = res[(res.target == target) & (res.horizon != 'all')]
        for k in BASELINES + ('LGBM',):
            rr = r[r.method == k]
            ax.plot(rr.horizon.astype(int), rr.brier, marker='o', label=METHOD_LABEL[k], color=colors[k], lw=2)
        ax.set_title(f'P({target} unavailable) - Brier on tune split (lower is better)')
        ax.set_xlabel('horizon (minutes)')
        ax.set_ylabel('Brier score')
        ax.grid(alpha=.3)
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(fig_dir / 'brier_by_horizon.png', dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    for ax, target in zip(axes, TARGETS):
        d, p = df, preds_by_target[target]
        m = (d['horizon_minutes'] == 30).to_numpy()
        y = d[LABEL_COLUMN[target]].to_numpy()[m]
        for k in ('B1cal', 'B2', 'LGBM_raw', 'LGBM'):
            t = pd.DataFrame(metrics.reliability_table(p[k][m], y)).dropna()
            t = t[t.n >= 50]
            ax.plot(t.mean_pred, t.observed_rate, marker='o', label=f"{METHOD_LABEL[k]} (ECE {metrics.ece(p[k][m], y):.3f})", color=colors[k])
        ax.plot([0, 1], [0, 1], ls='--', color='black', lw=1)
        ax.set_title(f'{target} unavailable, 30-min horizon')
        ax.set_xlabel('predicted probability')
        ax.set_ylabel('observed frequency')
        ax.legend(fontsize=8)
        ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(fig_dir / 'reliability_30min.png', dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, target in zip(axes, TARGETS):
        imp = importance[importance.target == target].sort_values('gain_share').tail(12)
        ax.barh(imp.feature, imp.gain_share, color=colors['LGBM'])
        ax.set_title(f'{target} model - share of total split gain')
    fig.tight_layout()
    fig.savefig(fig_dir / 'feature_importance.png', dpi=160)
    plt.close(fig)

    for (target, kind), (station, day) in examples.items():
        m = ((df['station_id'] == station) & (df['service_day'] == day) & (df['horizon_minutes'] == 30)).to_numpy()
        d = df[m]
        tt = pd.to_datetime(d['request_time'] + 1800, unit='s', utc=True).dt.tz_convert('America/Chicago')
        p = preds_by_target[target]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.step(tt, d[LABEL_COLUMN[target]], where='mid', color='black', lw=1.2, label='observed unavailable (label)')
        ax.plot(tt, p['B1'][m], color=colors['B1'], lw=1.5, ls='--', label='B1 persistence')
        ax.plot(tt, p['B1cal'][m], color=colors['B1cal'], lw=1.2, label='B1-cal')
        ax.plot(tt, p['B2'][m], color=colors['B2'], lw=1.5, label='B2 historical rate')
        ax.plot(tt, p['LGBM'][m], color=colors['LGBM'], lw=2, label='LightGBM + sigmoid')
        ax.set_ylim(-.05, 1.05)
        ax.set_ylabel(f'P({target} unavailable)')
        ax.set_title(f'{kind}: {NAMES.get(station, station)} ({station}), {day}, 30-min horizon')
        ax.legend(fontsize=7, loc='upper center', bbox_to_anchor=(0.5, -0.22), ncols=5, frameon=False)
        ax.grid(alpha=.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(fig_dir / f'example_{target}_{kind}.png', dpi=160)
        plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data-root', type=Path, required=True, help='external chicago_historical_2021_sample root')
    p.add_argument('--reports', type=Path, default=PROJECT / 'reports/forecaster_m3')
    p.add_argument('--model-dir', type=Path, default=None, help='default: <data-root>/models/forecaster_v0_m3')
    p.add_argument('--skip-ablations', action='store_true')
    args = p.parse_args()
    t0 = time.time()
    schema = load_schema()
    columns = feature_columns(schema)
    model_dir = args.model_dir or args.data_root / 'models/forecaster_v0_m3'
    root = pipeline_root(args.data_root)

    train = load_split(args.data_root, ['train'], schema)
    tune = load_split(args.data_root, ['tune'], schema)
    lo, hi = train_bounds()
    cutoff = hi - INNER_DAYS * 86400
    fit_df = train[train['target_time'] < cutoff]
    inner_df = train[train['request_time'] >= cutoff]
    categories = sorted(train['station_id'].unique())
    print(f'loaded train={len(train):,} (fit {len(fit_df):,} / inner {len(inner_df):,}) tune={len(tune):,} in {time.time()-t0:.0f}s', flush=True)

    rates = pd.read_parquet(root / 'B2/heldout_training_fit_rates.parquet')
    models, preds_by_target, results, boots, slices, stations, importance, examples = {}, {}, [], [], [], [], [], {}
    for target in TARGETS:
        model = fit_target(fit_df, inner_df, target, columns, categories)
        models[target] = model
        preds = dict(B1=baselines.b1_persistence(tune, target),
                     B1cal=baselines.b1_calibrated(tune, baselines.fit_b1_calibrated(train, target), target), B2=baselines.b2_historical(tune, rates, target),
                     LGBM_raw=predict_target(model, tune, columns, categories, calibrated=False),
                     LGBM=predict_target(model, tune, columns, categories))
        if np.isnan(preds['B2']).any():
            raise ValueError('B2 table does not cover every tune station/cell')
        preds_by_target[target] = preds
        r, b = evaluate(tune, preds, target)
        results += r
        boots += b
        slices += slice_metrics(tune, preds, target)
        stations.append(station_metrics(tune, preds, target))
        gain = model.booster.feature_importance('gain', iteration=model.best_iteration)
        importance += [dict(target=target, feature=f, gain=float(g), gain_share=float(g / gain.sum())) for f, g in zip(model.booster.feature_name(), gain)]
        examples[(target, 'success')], examples[(target, 'failure')] = pick_examples(tune, preds, target)
        print(f'{target}: best_iter={model.best_iteration} calib a={model.calibrator.a:.3f} b={model.calibrator.b:.3f} ({time.time()-t0:.0f}s)', flush=True)

    ablations = []
    if not args.skip_ablations:
        variants = {'no_lag_features': [c for c in columns if not c.startswith(LAG_COLUMNS_PREFIX)],
                    'no_station_id': [c for c in columns if c != 'station_id'],
                    'current_state_only': ['horizon_minutes', 'num_bikes_available', 'num_docks_available', 'capacity', 'hour', 'weekday']}
        for target in TARGETS:
            y = tune[LABEL_COLUMN[target]].to_numpy()
            full = metrics.summary(preds_by_target[target]['LGBM'], y)
            ablations.append(dict(target=target, variant='full_model', n_features=len(columns), brier=full['brier'], ece=full['ece'], pr_auc=full['pr_auc']))
            for name, cols in variants.items():
                m = fit_target(fit_df, inner_df, target, cols, categories)
                s = metrics.summary(predict_target(m, tune, cols, categories), y)
                ablations.append(dict(target=target, variant=name, n_features=len(cols), brier=s['brier'], ece=s['ece'], pr_auc=s['pr_auc']))
                print(f'ablation {target} {name}: brier={s["brier"]:.5f} ({time.time()-t0:.0f}s)', flush=True)

    out = args.reports
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(out / 'metrics_by_horizon.csv', index=False)
    pd.DataFrame(boots).to_csv(out / 'bootstrap_vs_best_baseline.csv', index=False)
    pd.DataFrame(slices).to_csv(out / 'slice_metrics.csv', index=False)
    pd.concat(stations).to_csv(out / 'station_metrics_30min.csv', index=False)
    imp = pd.DataFrame(importance)
    imp.to_csv(out / 'feature_importance.csv', index=False)
    if ablations:
        pd.DataFrame(ablations).to_csv(out / 'ablations.csv', index=False)
    rel = []
    for target in TARGETS:
        m = (tune['horizon_minutes'] == 30).to_numpy()
        for k in ('B1cal', 'B2', 'LGBM_raw', 'LGBM'):
            rel += [dict(target=target, horizon=30, method=k, **r) for r in metrics.reliability_table(preds_by_target[target][k][m], tune[LABEL_COLUMN[target]].to_numpy()[m])]
    pd.DataFrame(rel).to_csv(out / 'reliability_30min.csv', index=False)
    plot_all(out, tune, results, preds_by_target, imp, examples)

    data_manifest = json.loads((PROJECT / 'reports/final_pipeline_audit/features/generated_manifest.json').read_text(encoding='utf-8'))
    meta = dict(fit_rows=len(fit_df), inner_rows=len(inner_df), inner_cutoff_utc=pd.Timestamp(cutoff, unit='s', tz='UTC').isoformat(),
                splits_read=['train', 'tune'], splits_not_read=['calibration', 'test'],
                calibration_note='Provisional sigmoid fit on last 14 train days; the final calibrator will be refit on the frozen calibration split',
                feature_schema_sha256=sha256(SCHEMA_PATH), data_generated_manifest_files=len(data_manifest['files']))
    manifest = save_bundle(model_dir, models, columns, categories, meta)
    pred_frame = tune[['row_id', 'station_id', 'request_time', 'horizon_minutes']].copy()
    for target in TARGETS:
        for k, v in preds_by_target[target].items():
            pred_frame[f'p_{target}_unavailable_{k}'] = v
    pred_frame.to_parquet(model_dir / 'tune_predictions.parquet', index=False)

    summary = dict(status='M3_preliminary_tune_split_results', model_version=manifest['version'],
                   rows=dict(fit=len(fit_df), inner=len(inner_df), tune=len(tune)),
                   tune_days=int(tune['service_day'].nunique()),
                   class_balance=dict(train={t: float(train[LABEL_COLUMN[t]].mean()) for t in TARGETS},
                                      tune={t: float(tune[LABEL_COLUMN[t]].mean()) for t in TARGETS}),
                   best_iteration={t: models[t].best_iteration for t in TARGETS},
                   calibrator={t: dict(a=models[t].calibrator.a, b=models[t].calibrator.b) for t in TARGETS},
                   overall=[b for b in boots if b['horizon'] == 'all'],
                   examples={f'{t}_{k}': list(v) for (t, k), v in examples.items()},
                   runtime_seconds=round(time.time() - t0, 1), model_dir=str(model_dir),
                   **{k: manifest[k] for k in ('params', 'library_versions', 'splits_read', 'splits_not_read', 'calibration_note', 'feature_schema_sha256')})
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary['overall'], indent=2))
    print(f'done in {time.time()-t0:.0f}s -> {out}')


if __name__ == '__main__':
    main()
