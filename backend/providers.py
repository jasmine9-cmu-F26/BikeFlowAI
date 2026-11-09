"""Replay reads features only. Live keeps its own GBFS history; fixture is explicit."""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import HORIZONS, PROJECT, registry
from .policy import Policy

ZONE = ZoneInfo('America/Chicago')
DATA_ROOT = Path(os.environ.get('BIKEFLOW_DATA_ROOT', str(Path.home() / 'Documents/BikeFlowAI-data/divvy/chicago_historical_2021_sample')))


def local_time(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONE)
    return dt.astimezone(ZONE)


class Providers:
    def __init__(self, root=DATA_ROOT):
        self.root = root
        self.stations = registry()
        self.service = self.b2 = None
        self.policy = Policy(root)
        self.error = None
        self.lock = threading.RLock()
        self.history = deque()
        self.last_fetch = 0
        self.live_error = 'Live feed has not been fetched yet.'
        self.stop = threading.Event()
        self.thread = None
        self._load()

    def _load(self):
        try:
            sys.path.insert(0, str(PROJECT / 'scripts/model'))
            from replay_forecast import build_service
            from bikeflow_model.forecaster import ForecasterService
            self.service = build_service(self.root, None)
            self.b2 = ForecasterService(None, self.service.b2)
        except Exception as exc:
            self.error = f'Model runtime unavailable: {type(exc).__name__}: {exc}'

    def health(self):
        status = self.service.status() if self.service else dict(status='unavailable', active_method='unavailable', errors=[self.error])
        return dict(**status, replay_data_ready=any((self.root / 'processed/final_pipeline_v1/features').glob('*.parquet')),
                    fixture_available=True, live_enabled=os.environ.get('BIKEFLOW_LIVE', '1') != '0',
                    live_cache_ready=bool(self.history), live_error=self.live_error,
                    model_version=getattr(self.service, 'version', None), planner_version='decision-pair-v1',
                    rl_ready=self.policy.ready(), rl_reason='Current-action PPO bridge; station origin, matching walk limit and decision-grid departure required.',
                    timezone='America/Chicago')

    def start(self):
        if os.environ.get('BIKEFLOW_LIVE', '1') == '0':
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=6)

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.refresh()
                self.live_error = None
            except Exception as exc:
                self.live_error = f'GBFS refresh failed: {type(exc).__name__}'
            self.stop.wait(60)

    def refresh(self):
        url = 'https://gbfs.divvybikes.com/gbfs/en/station_status.json'
        payload = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'BikeFlow-course-demo/1.0'}), timeout=2) as response:
                    payload = json.load(response)
                break
            except Exception:
                if attempt:
                    raise
        now = time.time()
        raw = {s['station_id']: s for s in payload['data']['stations']}
        fetched = {}
        for st in self.stations:
            r = raw.get(st['live_id'])
            if r is None:
                continue
            stamp = r.get('last_reported', payload.get('last_updated', 0))
            if isinstance(stamp, str):
                stamp = local_time(stamp).timestamp()
            stamp = min(float(stamp), now)
            fetched[st['id']] = dict(id=st['id'], bikes=int(r['num_bikes_available']), docks=int(r['num_docks_available']),
                                    snapshot_time=stamp, pickup=bool(r.get('is_installed') and r.get('is_renting')),
                                    return_=bool(r.get('is_installed') and r.get('is_returning')))
        with self.lock:
            self.history.append((now, fetched))
            self.last_fetch = now
            while self.history and self.history[0][0] < now-4500:
                self.history.popleft()

    def snapshot(self, mode, when, scenario='normal'):
        if mode == 'fixture':
            return self.fixture(when, scenario)
        if mode == 'replay':
            return self.replay(when)
        return self.live()

    def fixture(self, when, scenario):
        """Synthetic, deterministic UI fixtures. Never described as trained predictions."""
        q = local_time(when)
        stations = []
        for i, st in enumerate(self.stations):
            bikes, docks = (i*7+3) % 19, (i*3+4) % 17
            risk = .12 if i % 3 == 0 else .92
            table = {h: dict(p_bike=round(max(.05, risk-.001*h), 3), p_dock=round(.88-.001*h, 3)) for h in HORIZONS}
            stations.append(dict(**st, bikes=bikes, docks=docks, pickup=True, return_=True,
                                 data_age_seconds=120 if scenario != 'stale' else 1800,
                                 forecast=table, b2={h: dict(p_bike=.72, p_dock=.78) for h in HORIZONS}))
        for s in stations:
            s['return'] = s.pop('return_')
            if scenario == 'stale':
                s['forecast'], s['b2'] = {}, {}
        return dict(mode='fixture', decision_time=q.isoformat(), stations=stations, stale=scenario == 'stale',
                    active_method='B2_historical' if scenario == 'model-missing' else 'fixture',
                    model_version='synthetic-fixture-v1', warnings=['SYNTHETIC EXAMPLE: counts and probabilities are invented for UI testing; not model results.'])

    def _predict(self, df, age_limit):
        import pandas as pd
        from replay_forecast import forecast
        # Serialize model calls; max_age is shared and differs between providers.
        with self.lock:
            old = self.service.max_age
            self.service.max_age = age_limit
            try:
                data = forecast(self.service, df)
                b2 = self.b2.predict(df)
            finally:
                self.service.max_age = old
        out = []
        for st in data['stations']:
            rows = df[df.station_id == st['station_id']]
            first = rows.iloc[0]
            rates = {}
            for idx, row in rows.iterrows():
                rates[int(row.horizon_minutes)] = {
                    f'p_{target}': None if pd.isna(b2.loc[idx, f'p_{target}_available']) or first.base_age_seconds > age_limit
                    else round(float(b2.loc[idx, f'p_{target}_available']), 3) for target in ('bike', 'dock')}
            meta = next(s for s in self.stations if s['id'] == st['station_id'])
            operating = bool(first.is_in_service)
            out.append(dict(**meta, bikes=st['bikes_now'], docks=st['docks_now'], capacity=int(first.capacity), pickup=operating, return_=operating,
                            data_age_seconds=st['data_age_seconds'], forecast=st['horizons'], b2=rates))
        for st in out:
            st['return'] = st.pop('return_')
        return out

    def replay(self, when):
        if not self.health()['replay_data_ready']:
            raise ValueError('Replay data not prepared. Set BIKEFLOW_DATA_ROOT to the audited data directory; example mode is available separately.')
        if self.service is None:
            raise ValueError(self.error)
        from replay_forecast import load_request
        import pandas as pd
        try:
            df = load_request(self.root, pd.Timestamp(local_time(when)), with_labels=False)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc
        if df.empty:
            raise ValueError('No causal station history at the selected time.')
        # q is the feature grid time, not the requested wall clock.
        q = datetime.fromtimestamp(int(df.request_time.iloc[0]), ZONE)
        return dict(mode='replay', decision_time=q.isoformat(), stations=self._predict(df, 900), stale=False,
                    active_method=self.service.status()['active_method'], model_version=getattr(self.service, 'version', None),
                    warnings=['Historical replay of summer 2021; travel times and availability are estimates.'])

    def live(self):
        q = datetime.now(ZONE)
        with self.lock:
            history = list(self.history)
        if not history:
            return dict(mode='live', decision_time=q.isoformat(), stations=[], stale=True, active_method='unavailable',
                        model_version=None, warnings=[self.live_error or 'Live cache not ready.'])
        current = history[-1][1]
        stations = []
        for st in self.stations:
            r = current.get(st['id'])
            if r:
                stations.append(dict(**st, bikes=r['bikes'], docks=r['docks'], pickup=r['pickup'],
                                     return_=r['return_'], data_age_seconds=int(q.timestamp()-r['snapshot_time']), forecast={}, b2={}))
        for s in stations:
            s['return'] = s.pop('return_')
        warnings = ['Live predictions use a model trained on summer 2021; current performance is not established.']
        active = 'unavailable'
        if self.service is not None:
            try:
                df = self.live_features(q, history)
                predicted = {s['id']: s for s in self._predict(df, 300)}
                for s in stations:
                    p = predicted.get(s['id'], {})
                    s['forecast'], s['b2'] = p.get('forecast', {}), p.get('b2', {})
                active = self.service.status()['active_method']
            except Exception as exc:
                warnings.append(f'Live feature inference unavailable: {type(exc).__name__}.')
        else:
            warnings.append(self.error)
        if any(s['data_age_seconds'] > 300 for s in stations):
            warnings.append('Stations older than five minutes are excluded from planning; last-known counts remain visible.')
        return dict(mode='live', decision_time=q.isoformat(), stations=stations,
                    stale=all(s['data_age_seconds'] > 300 for s in stations) if stations else True,
                    active_method=active, model_version=getattr(self.service, 'version', None), warnings=warnings)

    def live_features(self, q, history):
        import pandas as pd
        from bikeflow_model.data import add_derived
        rows = []
        now = q.timestamp()
        for sid, current in history[-1][1].items():
            capacity = current['bikes'] + current['docks']
            base = dict(station_id=sid, request_time=int(now), base_age_seconds=now-current['snapshot_time'],
                        num_bikes_available=current['bikes'], num_docks_available=current['docks'], capacity=capacity,
                        docks_in_service=capacity, is_in_service=current['pickup'] or current['return_'],
                        hour=q.hour, weekday=q.weekday(), is_weekend=q.weekday() >= 5, capacity_inconsistent=False)
            for lag in (10, 30, 60):
                # Match by observation timestamp, never by poll timestamp or a future value.
                candidates = [batch[sid] for _, batch in history if sid in batch and batch[sid]['snapshot_time'] <= now-lag*60]
                previous = max(candidates, key=lambda r: r['snapshot_time']) if candidates else None
                missing = previous is None or now-lag*60-previous['snapshot_time'] > 900
                base.update({f'bike_delta_{lag}m': math.nan if missing else current['bikes']-previous['bikes'],
                             f'dock_delta_{lag}m': math.nan if missing else current['docks']-previous['docks'],
                             f'lag_{lag}m_missing': missing,
                             f'lag_{lag}m_age_seconds': math.nan if missing else now-lag*60-previous['snapshot_time'],
                             f'lag_{lag}m_in_service': math.nan if missing else previous['pickup'] or previous['return_']})
            rows.extend(dict(**base, horizon_minutes=h) for h in HORIZONS)
        return add_derived(pd.DataFrame(rows))
