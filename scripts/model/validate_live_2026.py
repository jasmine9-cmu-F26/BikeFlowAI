"""Does the summer-2021 forecaster still work on current (2026) Divvy data?

Replays the full-GBFS collector output (current_validation/) for the 32 app
stations on a 10-minute decision grid. Features come from the application's own
live feature builder (backend.providers.Providers.live_features), so this tests
exactly what Live mode serves. Labels follow the training rule: the nearest
station observation after the decision within +-5 minutes of decision + horizon;
bike (dock) unavailable = 0 bikes (docks) or the station is not
installed+renting (installed+returning). Rows whose base observation is older
than 15 minutes are dropped, as in training.

Time: collector timestamps are absolute (epoch / UTC). Hour, weekday, B2 keys
and service days use America/Chicago local time via IANA zoneinfo. As in the
historical pipeline (bikeflow_data.temporal.dst_intervals), rows whose decision
or target local time is ambiguous or nonexistent around a DST change (e.g. the
repeated 01:00-02:00 on 2026-11-01) are excluded and counted.

Compares the bundled LightGBM+sigmoid forecaster with B1 persistence and B2
(2021 training-week rates), next to the 2021 tune results. Outputs go to
reports/live_validation_2026/. Nothing is trained or tuned on this data.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'scripts/model')]

from backend.artifacts import resolve_data_root  # noqa: E402
from backend.core import HORIZONS, distance, registry  # noqa: E402
from backend.providers import ZONE, Providers  # noqa: E402
from bikeflow_model.baselines import b1_persistence, b2_historical  # noqa: E402
from bikeflow_model.forecaster import ForecasterService  # noqa: E402
from bikeflow_model.metrics import day_block_bootstrap, reliability_table, summary  # noqa: E402

STEP = 600          # decision grid, seconds
MAX_AGE = 900       # base observation age limit, as in training
LABEL_TOL = 300     # +-5 minutes
HISTORY = 4500      # the app keeps 75 minutes of polls
TARGETS = ('bike', 'dock')


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def load_polls(root: Path, stations, cache: Path):
    """One record per (poll, app station), the same fields Live mode keeps."""
    if cache.exists():
        return pd.read_parquet(cache)
    meta_cache, rows = {}, []
    polls = [json.loads(line) for line in (root / 'polls.jsonl').open(encoding='utf-8')]
    polls = [p for p in polls if p.get('status') == 'ok' and p.get('snapshot_path')]
    for i, poll in enumerate(polls):
        received = utc(poll['status_capture']['received_at_utc'])
        mpath = poll['metadata_path']
        if mpath not in meta_cache:
            with gzip.open(root / mpath, 'rt', encoding='utf-8') as f:
                meta_cache[mpath] = {s['station_id']: s for s in json.load(f)['data']['stations']}
        meta = meta_cache[mpath]
        with gzip.open(root / poll['snapshot_path'], 'rt', encoding='utf-8') as f:
            payload = json.load(f)
        raw = {s['station_id']: s for s in payload['data']['stations']}
        published = payload.get('last_updated', received)
        for st in stations:
            r, m = raw.get(st['live_id']), meta.get(st['live_id'])
            if r is None or m is None:
                continue
            stamp = min(float(r.get('last_reported', published)), float(published), received)
            mapped = distance(st, m) <= 50
            rows.append(dict(poll=i, poll_time=received, id=st['id'], snapshot_time=stamp,
                             bikes=int(r['num_bikes_available']), docks=int(r['num_docks_available']),
                             capacity=int(m['capacity']),
                             pickup=bool(mapped and r.get('is_installed') and r.get('is_renting')),
                             return_=bool(mapped and r.get('is_installed') and r.get('is_returning'))))
        if i % 1000 == 0:
            print(f'parsed {i}/{len(polls)} polls', file=sys.stderr)
    df = pd.DataFrame(rows)
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def dst_ambiguous(epoch_seconds) -> bool:
    """Local Chicago wall time that occurs twice (fall back) or is skipped (spring forward)."""
    dt = datetime.fromtimestamp(float(epoch_seconds), ZONE)
    return dt.utcoffset() != dt.replace(fold=1 - dt.fold).utcoffset()


def build_rows(obs: pd.DataFrame):
    """Features via the app's live builder at every grid time, plus outcome labels."""
    polls = obs.groupby('poll')
    batches = [(float(g.poll_time.iloc[0]),
                {r.id: dict(bikes=r.bikes, docks=r.docks, capacity=r.capacity, snapshot_time=r.snapshot_time,
                            pickup=r.pickup, return_=r.return_) for r in g.itertuples()})
               for _, g in polls]
    batches.sort(key=lambda b: b[0])
    times = [b[0] for b in batches]
    # Per-station observation series for labels (deduplicated by report time).
    series = {}
    for sid, g in obs.sort_values('snapshot_time').drop_duplicates(['id', 'snapshot_time']).groupby('id'):
        series[sid] = (g.snapshot_time.to_numpy(float), g.bikes.to_numpy(), g.docks.to_numpy(),
                       g.pickup.to_numpy(bool), g.return_.to_numpy(bool))
    start = math.ceil((times[0] + 3600) / STEP) * STEP
    end = times[-1] - 3600 - LABEL_TOL
    features, labels = [], []
    for q in np.arange(start, end, STEP):
        k = bisect_right(times, q)
        history = [b for b in batches[max(0, k - 60):k] if b[0] >= q - HISTORY]
        if not history:
            continue
        when = datetime.fromtimestamp(q, ZONE)
        df = Providers.live_features(None, when, history)
        df = df[df.base_age_seconds <= MAX_AGE]
        if df.empty:
            continue
        lab = []
        for r in df.itertuples():
            t, bikes, docks, renting, returning = series[r.station_id]
            target = q + 60 * int(r.horizon_minutes)
            lo = np.searchsorted(t, q, side='right')
            j = np.searchsorted(t, target)
            best = None
            for c in (j - 1, j):
                if lo <= c < len(t) and abs(t[c] - target) <= LABEL_TOL and (best is None or abs(t[c] - target) < abs(t[best] - target)):
                    best = c
            if best is None:
                lab.append((np.nan, np.nan, np.nan))
            else:
                lab.append((float(bikes[best] == 0 or not renting[best]), float(docks[best] == 0 or not returning[best]),
                            t[best] - target))
        df = df.assign(bike_unavailable=[x[0] for x in lab], dock_unavailable=[x[1] for x in lab],
                       target_offset_seconds=[x[2] for x in lab])
        features.append(df)
    out = pd.concat(features, ignore_index=True)
    out = out[out.bike_unavailable.notna()]
    target = out.request_time + 60 * out.horizon_minutes.astype(int)
    dst = out.request_time.map(dst_ambiguous) | target.map(dst_ambiguous)
    out.attrs['dst_excluded_rows'] = int(dst.sum())
    out.attrs['dst_excluded_local'] = sorted({datetime.fromtimestamp(float(t), ZONE).isoformat()
                                              for t in out.request_time[dst]})[:: max(1, int(dst.sum() // 2000) or 1)][:4]
    return out[~dst].reset_index(drop=True)


def evaluate(df: pd.DataFrame, service: ForecasterService, b2_rates: pd.DataFrame):
    pred = service.predict(df)
    rows, boot, reliability = [], [], {}
    for target in TARGETS:
        y = df[f'{target}_unavailable'].to_numpy(float)
        methods = {'B1': b1_persistence(df, target), 'B2': b2_historical(df, b2_rates, target),
                   'LGBM': 1.0 - pred[f'p_{target}_available'].to_numpy(float)}
        ok = np.all([~np.isnan(p) for p in methods.values()], axis=0)
        for h in ['all', *HORIZONS]:
            m = ok & ((df.horizon_minutes == h).to_numpy() if h != 'all' else True)
            for name, p in methods.items():
                rows.append(dict(target=target, horizon=h, method=name, **summary(p[m], y[m])))
            if h == 'all' or h in (10, 30, 60):
                ref = min(('B1', 'B2'), key=lambda n: np.mean((methods[n][m] - y[m]) ** 2))
                b = day_block_bootstrap(methods['LGBM'][m], methods[ref][m], y[m], df.service_day.to_numpy()[m], n_boot=2000)
                boot.append(dict(target=target, horizon=h, reference=ref, **b))
        m30 = ok & (df.horizon_minutes == 30).to_numpy()
        reliability[target] = reliability_table(methods['LGBM'][m30], y[m30])
    return pd.DataFrame(rows), pd.DataFrame(boot), reliability


def plot(metrics: pd.DataFrame, tune: pd.DataFrame, path: Path):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, target in zip(axes, TARGETS):
        for method, color in (('B1', 'C0'), ('B2', 'C1'), ('LGBM', 'C2')):
            for frame, style, label in ((metrics, '-o', '2026 live'), (tune, ':s', '2021 tune')):
                r = frame[(frame.target == target) & (frame.method == method) & (frame.horizon != 'all')]
                ax.plot(r.horizon.astype(int), r.brier, style, color=color, label=f'{method} · {label}', ms=4)
        ax.set_title(f'{target} unavailable')
        ax.set_xlabel('horizon (min)')
        ax.set_ylabel('Brier (lower is better)')
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7)
    fig.suptitle('Summer-2021 forecaster on November 2026 live data vs. its 2021 tune results')
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--live-root', type=Path, required=True, help='collector output directory (current_validation/)')
    p.add_argument('--data-root', type=Path, help='model package (default: the bundled demo data)')
    p.add_argument('--cache', type=Path, default=PROJECT / '.local/live_validation/app32_polls.parquet')
    p.add_argument('--out', type=Path, default=PROJECT / 'reports/live_validation_2026')
    a = p.parse_args()
    root, _ = resolve_data_root(a.data_root)
    stations = registry()
    obs = load_polls(a.live_root, stations, a.cache)
    df = build_rows(obs)
    b2_rates = pd.read_parquet(root / 'processed/final_pipeline_v1/B2/heldout_training_fit_rates.parquet')
    service = ForecasterService(root / 'models/forecaster_v0_m3', b2_rates, max_input_age_seconds=MAX_AGE)
    metrics, boot, reliability = evaluate(df, service, b2_rates)
    a.out.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(a.out / 'metrics_by_horizon.csv', index=False)
    boot.to_csv(a.out / 'bootstrap_vs_best_baseline.csv', index=False)
    tune = pd.read_csv(PROJECT / 'reports/forecaster_m3/metrics_by_horizon.csv')
    tune = tune[tune.method.isin(['B1', 'B2', 'LGBM'])].copy()
    tune['horizon'] = tune.horizon.astype(str)
    metrics_s = metrics.assign(horizon=metrics.horizon.astype(str))
    plot(metrics_s, tune, a.out / 'brier_2026_vs_2021.png')
    span = obs.poll_time.agg(['min', 'max'])
    present = sorted(obs.id.unique())
    poll_gaps = np.diff(np.sort(obs.drop_duplicates('poll').poll_time.to_numpy()))
    report_age = (obs.poll_time - obs.snapshot_time)
    summary_json = dict(
        live_window_utc=[datetime.fromtimestamp(span[k], timezone.utc).isoformat() for k in ('min', 'max')],
        polls=int(obs.poll.nunique()), poll_interval_median_s=float(np.median(poll_gaps)), poll_interval_p99_s=float(np.percentile(poll_gaps, 99)),
        gaps_over_15min=int((poll_gaps > 900).sum()),
        app_stations_found=len(present), app_stations_missing=sorted({s['id'] for s in stations} - set(present)),
        report_age_median_s=float(report_age.median()), report_age_p90_s=float(report_age.quantile(.9)),
        rows=int(len(df)), decision_times=int(df.request_time.nunique()), service_days=int(df.service_day.nunique()),
        timezone='America/Chicago (IANA zoneinfo; collector timestamps are absolute)',
        dst_excluded_rows=df.attrs.get('dst_excluded_rows', 0),
        dst_excluded_decision_times_sample=df.attrs.get('dst_excluded_local', []),
        label_offset_abs_median_s=float(df.target_offset_seconds.abs().median()),
        base_rates={t: float(df[f'{t}_unavailable'].mean()) for t in TARGETS},
        tune_2021_base_rates={t: float(tune[(tune.target == t) & (tune.horizon == 'all') & (tune.method == 'LGBM')].base_rate.iloc[0]) for t in TARGETS},
        reliability_30min=reliability,
        model_version=getattr(service, 'version', None), b2='2021 training-week rates', trained_on_this_data=False)
    (a.out / 'summary.json').write_text(json.dumps(summary_json, indent=2, default=float) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary_json.items() if k != 'reliability_30min'}, indent=2, default=float))


if __name__ == '__main__':
    main()
