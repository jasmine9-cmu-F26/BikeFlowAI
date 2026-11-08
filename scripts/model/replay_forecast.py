"""Replay demo: calibrated availability forecasts for the app stations at a historical time.

Reads only the causal feature rows at the latest 10-minute grid request <= the
given time (same rows the model would see live), runs the serving wrapper with
its fallback chain, and optionally reveals the observed outcomes afterwards.

  python scripts/model/replay_forecast.py --data-root EXT --time "2021-07-20 08:00" --reveal
  python scripts/model/replay_forecast.py --data-root EXT --time "2021-07-20 08:00" --simulate model-missing
  python scripts/model/replay_forecast.py --data-root EXT --time "2021-07-20 08:00" --simulate stale-feed
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bikeflow_model import ZONE  # noqa: E402
from bikeflow_model.data import PROJECT, add_derived, pipeline_root  # noqa: E402
from bikeflow_model.forecaster import ForecasterService  # noqa: E402

HORIZONS = [10, 20, 30, 40, 50, 60]


def station_names():
    with (PROJECT / 'data/manifests/chicago/app_stations.csv').open(encoding='utf-8', newline='') as f:
        return {r['station_id']: r['historical_name'] for r in csv.DictReader(f)}


def load_request(data_root: Path, when: pd.Timestamp, stations=None, with_labels=False) -> pd.DataFrame:
    root = pipeline_root(data_root)
    epoch = int(when.tz_convert('UTC').timestamp())
    con = duckdb.connect()
    feats = str(root / 'features/*.parquet')
    request = con.execute('SELECT max(request_time) FROM read_parquet(?) WHERE request_time <= ? AND request_time > ? - 600', [feats, epoch, epoch]).fetchone()[0]
    if request is None:
        raise SystemExit(f'No causal feature rows within 10 minutes before {when}; request excluded (FR6).')
    q = 'SELECT * FROM read_parquet(?) WHERE request_time = ?'
    df = con.execute(q, [feats, request]).df()
    if with_labels:
        labels = con.execute('SELECT row_id, bike_unavailable, dock_unavailable, target_num_bikes, target_num_docks FROM read_parquet(?) WHERE request_time = ?',
                             [str(root / 'labels/*.parquet'), request]).df()
        df = df.merge(labels, on='row_id', how='left')
    con.close()
    if stations:
        df = df[df['station_id'].isin(stations)]
    return add_derived(df)


def forecast(svc: ForecasterService, df: pd.DataFrame) -> dict:
    preds = svc.predict(df)
    df = pd.concat([df, preds], axis=1)
    names = station_names()
    out = []
    for sid, g in df.sort_values('horizon_minutes').groupby('station_id'):
        first = g.iloc[0]
        item = dict(station_id=sid, name=names.get(sid, sid), bikes_now=int(first.num_bikes_available), docks_now=int(first.num_docks_available),
                    data_age_seconds=int(first.base_age_seconds), method=first.method,
                    horizons={int(r.horizon_minutes): dict(p_bike=None if pd.isna(r.p_bike_available) else round(float(r.p_bike_available), 3),
                                                           p_dock=None if pd.isna(r.p_dock_available) else round(float(r.p_dock_available), 3))
                              for r in g.itertuples()})
        if 'bike_unavailable' in g:
            item['observed'] = {int(r.horizon_minutes): dict(bikes=r.target_num_bikes, docks=r.target_num_docks) for r in g.itertuples()}
        out.append(item)
    request = pd.Timestamp(int(df['request_time'].iloc[0]), unit='s', tz='UTC').tz_convert(ZONE)
    return dict(mode='replay', historical_timestamp=request.isoformat(), service=svc.status(), stations=out)


def build_service(data_root: Path, simulate: str | None, max_age: int = 900) -> ForecasterService:
    model_dir = data_root / 'models/forecaster_v0_m3'
    b2_path = pipeline_root(data_root) / 'B2/heldout_training_fit_rates.parquet'
    rates = pd.read_parquet(b2_path) if b2_path.exists() and simulate != 'all-missing' else None
    if simulate in ('model-missing', 'all-missing'):
        model_dir = data_root / 'models/__missing__'
    return ForecasterService(model_dir, rates, max_input_age_seconds=max_age)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--time', required=True, help='historical local Chicago time, e.g. "2021-07-20 08:00"')
    p.add_argument('--stations', nargs='*', help='station_id values (default: all app stations)')
    p.add_argument('--limit', type=int, default=8, help='stations printed, riskiest (lowest 30-min availability) first')
    p.add_argument('--reveal', action='store_true', help='also print observed outcomes (offline scoring only)')
    p.add_argument('--simulate', choices=['model-missing', 'all-missing', 'stale-feed'])
    p.add_argument('--json', action='store_true')
    args = p.parse_args()
    when = pd.Timestamp(args.time).tz_localize(ZONE) if pd.Timestamp(args.time).tzinfo is None else pd.Timestamp(args.time)
    df = load_request(args.data_root, when, args.stations, with_labels=args.reveal)
    if args.reveal and (df['split'] == 'test').any():
        raise SystemExit('Outcomes in the final test split are reserved for final reporting; use a train/tune date with --reveal.')
    if args.simulate == 'stale-feed':
        df['base_age_seconds'] = 1800.0
    result = forecast(build_service(args.data_root, args.simulate), df)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    s = result['service']
    print(f"replay @ {result['historical_timestamp']}  service={s['status']}  method={s['active_method']}")
    for e in s['errors']:
        print(f'  ! {e}')
    head = f"{'station':34s} {'now b/d':>8s} " + ' '.join(f'{h:>3d}m b/d ' for h in HORIZONS)
    print(head)
    print('-' * len(head))
    def risk(st):
        v = st['horizons'].get(30) or {}
        return 2.0 if v.get('p_bike') is None else min(v['p_bike'], v['p_dock'])
    for st in sorted(result['stations'], key=risk)[:args.limit]:
        cells = []
        for h in HORIZONS:
            v = st['horizons'].get(h)
            cells.append('   --    ' if v is None or v['p_bike'] is None else f"{v['p_bike']:.2f}/{v['p_dock']:.2f}")
        print(f"{st['name'][:34]:34s} {st['bikes_now']:>3d}/{st['docks_now']:<4d} " + ' '.join(f'{c:>9s}' for c in cells))
        if args.reveal and 'observed' in st:
            obs = ' '.join(f"{'' if st['observed'].get(h) is None else '%d/%d' % (st['observed'][h]['bikes'], st['observed'][h]['docks']):>9s}" for h in HORIZONS)
            print(f"{'   observed bikes/docks':34s} {'':8s} {obs}")
    print(f"methods: {sorted({st['method'] for st in result['stations']})}  (P = probability a bike/dock is available)")


if __name__ == '__main__':
    main()
