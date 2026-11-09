"""Integration with synthetic Parquet and actual LightGBM serving, never raw data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np

from backend.core import Planner, HORIZONS
from backend.providers import Providers, local_time


class ReplayProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pipeline = self.root / 'processed/final_pipeline_v1'
        for name in ['features', 'labels', 'B2']:
            (self.pipeline / name).mkdir(parents=True)
        self.q = local_time('2021-07-20T08:06:00-05:00')
        self.provider = Providers(self.root)
        self.stations = self.provider.stations
        from bikeflow_model.data import feature_columns
        rows, labels, rates = [], [], []
        for st in self.stations:
            for h in HORIZONS:
                row = {c:0 for c in feature_columns()}
                row.update(station_id=st['id'], horizon_minutes=h, request_time=int(self.q.timestamp()),
                           split='tune', row_id=f"{st['id']}|{int(self.q.timestamp())}|{h}",
                           num_bikes_available=5, num_docks_available=8, capacity=20, docks_in_service=13,
                           is_in_service=True, base_age_seconds=60, hour=8, weekday=1)
                rows.append(row)
                labels.append(dict(row_id=row['row_id'], request_time=row['request_time'], bike_unavailable=0,
                                   dock_unavailable=1, target_num_bikes=3, target_num_docks=0))
            for weekday in range(7):
                for hour in range(24):
                    rates.append(dict(station_id=st['id'], weekday=weekday, hour=hour,
                                      bike_available_rate=.75, dock_available_rate=.9))
        self.features = pd.DataFrame(rows)
        self.features.to_parquet(self.pipeline / 'features/part_tune.parquet')
        pd.DataFrame(labels).to_parquet(self.pipeline / 'labels/part_tune.parquet')
        pd.DataFrame(rates).to_parquet(self.pipeline / 'B2/heldout_training_fit_rates.parquet')
        self.provider = Providers(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_parquet_missing_model_falls_back_to_b2(self):
        snap = self.provider.replay(self.q)
        self.assertEqual(snap['active_method'], 'B2_historical')
        self.assertEqual(len(snap['stations']),32)
        self.assertAlmostEqual(snap['stations'][0]['forecast'][10]['p_bike'], .75)
        snap['stations'][0]['pickup'] = False
        self.assertTrue(self.provider.replay(self.q)['stations'][0]['pickup'], 'cache must return independent copies')

    def test_plan_never_reads_labels(self):
        (self.pipeline / 'labels/part_tune.parquet').write_bytes(b'INTENTIONALLY UNREADABLE OUTCOMES')
        snap = self.provider.replay(self.q)
        p = Planner().plan(dict(origin='chicago:14', destination='chicago:21', departure_time=self.q,
                                method='B3', walk_limit_minutes=10), snap)
        self.assertEqual(p['status'],'ok')
        self.assertEqual(p['actual_method'],'B2')

    def test_reveal_is_separate_and_test_split_reserved(self):
        attempts = [dict(station_id='chicago:14', horizon_minutes=10, phase='return')]
        r = self.provider.reveal(self.q, attempts)
        self.assertEqual(r['outcomes'][0]['status'], 'unavailable')
        self.assertEqual(r['outcomes'][0]['observed'], 0)
        with self.assertRaisesRegex(ValueError, 'tune split'):
            self.provider.reveal(local_time('2021-08-10T08:00:00-05:00'), attempts)
        with self.assertRaisesRegex(ValueError, 'reserved'):
            self.provider.replay(local_time('2021-08-10T08:00:00-05:00'))

    def test_model_bundle_loads_and_serves_actual_booster(self):
        import lightgbm as lgb
        from bikeflow_model.data import feature_columns, to_matrix
        from bikeflow_model.forecaster import TrainedTarget, Sigmoid, save_bundle
        cols = feature_columns()
        categories = [s['id'] for s in self.stations]
        x = to_matrix(self.features, cols, categories)
        train = lgb.Dataset(x,label=np.arange(len(x)) % 2, categorical_feature=['station_id'])
        booster = lgb.train(dict(objective='binary',verbosity=-1,num_threads=1,min_data_in_leaf=1),train,num_boost_round=2)
        target = TrainedTarget(booster,Sigmoid(),2)
        save_bundle(self.root / 'models/forecaster_v0_m3',dict(bike=target,dock=target),cols,categories,{})
        provider = Providers(self.root)
        self.assertEqual(provider.health()['status'],'ready')
        snap = provider.replay(self.q)
        self.assertEqual(snap['active_method'],'lightgbm_sigmoid')
        self.assertTrue(all(0 <= s['forecast'][10]['p_bike'] <= 1 for s in snap['stations']))


class LiveProviderTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Providers,'_load'):
            self.provider = Providers(Path('unused'))

    def test_discovery_flags_capacity_and_report_freshness(self):
        p = self.provider
        st = p.stations[0]
        now = 1700000000
        info = dict(data=dict(stations=[dict(station_id=st['live_id'],lat=st['lat'],lon=st['lon'],capacity=25)]))
        status = dict(last_updated=now-30,data=dict(stations=[dict(station_id=st['live_id'],last_reported=now-60,
                      num_bikes_available=4,num_docks_available=10,is_installed=1,is_renting=0,is_returning=1)]))
        discovery = dict(data=dict(en=dict(feeds=[dict(name='station_information',url='https://gbfs.divvybikes.com/info'),
                                                                dict(name='station_status',url='https://gbfs.divvybikes.com/status')])))
        with patch.object(p,'fetch',side_effect=[discovery,info,status]),patch('backend.providers.time.time',return_value=now):
            p.refresh()
        r=p.history[-1][1][st['id']]
        self.assertFalse(r['pickup'])
        self.assertTrue(r['return_'])
        self.assertEqual(r['capacity'],25)
        self.assertEqual(r['snapshot_time'],now-60)
        # Full feed polls remain in history even when stock is unchanged.
        with patch.object(p,'fetch',return_value=status),patch('backend.providers.time.time',return_value=now+60):
            p.refresh()
        self.assertEqual(len(p.history),2)

    def test_live_lags_use_only_past_reports_and_keep_missing(self):
        p = self.provider
        q = local_time('2021-07-20T08:00:00-05:00')
        sid = p.stations[0]['id']
        now=q.timestamp()
        base=dict(bikes=5,docks=8,capacity=20,pickup=True,return_=True,snapshot_time=now-20)
        prior=dict(base,bikes=7,docks=6,snapshot_time=now-620)
        history=[(now-600,{sid:prior}),(now,{sid:base})]
        rows=p.live_features(q,history)
        first=rows.iloc[0]
        self.assertEqual(first.bike_delta_10m,-2)
        self.assertEqual(first.lag_10m_age_seconds,20)
        self.assertTrue(first.lag_60m_missing)
        self.assertTrue(pd.isna(first.bike_delta_60m))
        self.assertEqual(first.capacity,20)
        self.assertEqual(first.docks_in_service,13)


if __name__=='__main__':
    unittest.main()
