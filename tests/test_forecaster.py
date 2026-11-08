"""Synthetic forecaster, baseline, metric and serving-fallback regressions (offline, no real data)."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/model'))
try:
    import lightgbm  # noqa: F401
    HAVE_LGBM = True
except Exception:  # pragma: no cover - CI without model extras
    HAVE_LGBM = False

from bikeflow_model import metrics  # noqa: E402
from bikeflow_model.data import add_derived, feature_columns, load_schema  # noqa: E402
from bikeflow_model.baselines import b1_persistence, b2_historical  # noqa: E402

STATIONS = ['chicago:a', 'chicago:b', 'chicago:c']


def synthetic(n_requests=1500, seed=0, start=1620018360):
    """Stations drain linearly with a strong lag signal; label = empty after horizon."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_requests):
        sid = STATIONS[i % 3]
        t = start + (i // 3) * 600
        bikes = int(rng.integers(0, 8))
        trend = float(rng.normal(0, 2))
        for h in (10, 20, 30, 40, 50, 60):
            future = bikes + trend * h / 10 + rng.normal(0, 0.7)
            rows.append(dict(row_id=f'{sid}|{t}|{h}', split='train', request_time=t, station_id=sid, horizon_minutes=h,
                             num_bikes_available=float(bikes), num_docks_available=float(15 - bikes), capacity=15.0,
                             docks_in_service=15.0, is_in_service=True, base_age_seconds=60.0, hour=0, weekday=0,
                             is_weekend=False, capacity_inconsistent=False,
                             bike_delta_10m=trend, dock_delta_10m=-trend, lag_10m_missing=False, lag_10m_age_seconds=30.0, lag_10m_in_service=True,
                             bike_delta_30m=3 * trend, dock_delta_30m=-3 * trend, lag_30m_missing=False, lag_30m_age_seconds=30.0, lag_30m_in_service=True,
                             bike_delta_60m=np.nan, dock_delta_60m=np.nan, lag_60m_missing=True, lag_60m_age_seconds=np.nan, lag_60m_in_service=None,
                             target_time=t + h * 60, target_offset_seconds=0,
                             bike_unavailable=int(future <= 0.5), dock_unavailable=int(future >= 14.5)))
    df = add_derived(pd.DataFrame(rows))
    hours = pd.to_datetime(df['request_time'], unit='s', utc=True).dt.tz_convert('America/Chicago')
    df['hour'], df['weekday'] = hours.dt.hour, hours.dt.day_of_week
    return df


def rates_table(value=0.8):
    return pd.DataFrame([dict(station_id=s, weekday=w, hour=h, bike_available_rate=value, dock_available_rate=0.95)
                         for s in STATIONS for w in range(7) for h in range(24)])


class MetricTests(unittest.TestCase):
    def test_brier_and_perfect_calibration(self):
        y = np.array([0, 1, 0, 1])
        self.assertAlmostEqual(metrics.brier([0, 1, 0, 1], y), 0.0)
        self.assertAlmostEqual(metrics.brier([0.5] * 4, y), 0.25)
        self.assertAlmostEqual(metrics.ece([0.5] * 4, y), 0.0)
        self.assertAlmostEqual(metrics.ece([0.95] * 4, y), 0.45)

    def test_day_block_bootstrap_is_paired_and_directional(self):
        rng = np.random.default_rng(1)
        y = rng.integers(0, 2, 4000)
        days = np.repeat(np.arange(20), 200)
        same = metrics.day_block_bootstrap(np.full(4000, .3), np.full(4000, .3), y, days, n_boot=200)
        self.assertEqual(same['brier_diff'], 0.0)
        self.assertEqual(same['brier_diff_ci95'], [0.0, 0.0])
        better = metrics.day_block_bootstrap(np.where(y == 1, .8, .2), np.full(4000, .5), y, days, n_boot=200)
        self.assertLess(better['brier_diff_ci95'][1], 0)
        self.assertEqual(better['days'], 20)


class BaselineTests(unittest.TestCase):
    def test_b1_predicts_unavailable_only_when_count_zero(self):
        df = pd.DataFrame(dict(num_bikes_available=[0, 1, 5], num_docks_available=[3, 0, 2]))
        self.assertEqual(b1_persistence(df, 'bike').tolist(), [1.0, 0.0, 0.0])
        self.assertEqual(b1_persistence(df, 'dock').tolist(), [0.0, 1.0, 0.0])

    def test_b2_uses_target_time_calendar_not_request_time(self):
        # 2021-05-03 23:55 Chicago (Monday) + 10 minutes -> Tuesday 00:05
        request = int(pd.Timestamp('2021-05-03 23:55', tz='America/Chicago').timestamp())
        df = add_derived(pd.DataFrame(dict(station_id=['chicago:a'], request_time=[request], horizon_minutes=[10])))
        self.assertEqual((df['target_weekday'][0], df['target_hour'][0]), (1, 0))
        rates = rates_table(0.8)
        rates.loc[(rates.weekday == 1) & (rates.hour == 0) & (rates.station_id == 'chicago:a'), 'bike_available_rate'] = 0.25
        self.assertAlmostEqual(b2_historical(df, rates, 'bike')[0], 0.75)

    def test_b1_calibrated_is_train_rate_by_count_and_horizon(self):
        from bikeflow_model.baselines import b1_calibrated, fit_b1_calibrated
        train = pd.DataFrame(dict(num_bikes_available=[0, 0, 0, 0, 1, 1, 30], horizon_minutes=[10] * 7, bike_unavailable=[1, 1, 1, 0, 0, 1, 0]))
        table = fit_b1_calibrated(train, 'bike')
        query = pd.DataFrame(dict(num_bikes_available=[0, 1, 25, 3], horizon_minutes=[10, 10, 10, 10]))
        # count 25 shares the capped cell with 30; unseen count 3 falls back to hard persistence (0).
        np.testing.assert_allclose(b1_calibrated(query, table, 'bike'), [0.75, 0.5, 0.0, 0.0])

    def test_b2_unknown_station_is_nan_for_fallback(self):
        df = add_derived(pd.DataFrame(dict(station_id=['chicago:zzz'], request_time=[1620018360], horizon_minutes=[10])))
        self.assertTrue(np.isnan(b2_historical(df, rates_table(), 'dock')[0]))


class SchemaTests(unittest.TestCase):
    def test_model_inputs_exclude_labels_lineage_and_ids(self):
        schema = load_schema()
        cols = set(feature_columns(schema))
        self.assertFalse(cols & set(schema['never_model_inputs']))
        self.assertFalse(cols & set(schema['lineage_columns']))
        self.assertNotIn('request_time', cols)


@unittest.skipUnless(HAVE_LGBM, 'lightgbm not installed')
class ForecasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from bikeflow_model.forecaster import fit_target, predict_target, save_bundle
        cls.columns = feature_columns()
        df = synthetic()
        cut = df['request_time'].quantile(0.6)
        cls.fit, cls.inner = df[df['request_time'] < cut], df[(df['request_time'] >= cut) & (df['request_time'] < df['request_time'].quantile(.8))]
        cls.held = df[df['request_time'] >= df['request_time'].quantile(.8)]
        cls.models = {t: fit_target(cls.fit, cls.inner, t, cls.columns, STATIONS, params=dict(num_threads=1, min_data_in_leaf=20)) for t in ('bike', 'dock')}
        cls.predict_target = staticmethod(predict_target)
        cls.tmp = Path(tempfile.mkdtemp())
        save_bundle(cls.tmp / 'model', cls.models, cls.columns, STATIONS, dict(test=True))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_learned_model_beats_persistence_on_trend_signal(self):
        y = self.held['bike_unavailable'].to_numpy()
        p = self.predict_target(self.models['bike'], self.held, self.columns, STATIONS)
        self.assertLess(metrics.brier(p, y), metrics.brier(b1_persistence(self.held, 'bike'), y))
        self.assertTrue(((p >= 0) & (p <= 1)).all())

    def test_saved_bundle_round_trips_to_identical_predictions(self):
        from bikeflow_model.forecaster import ForecasterService
        svc = ForecasterService(self.tmp / 'model', rates_table())
        self.assertEqual(svc.status()['status'], 'ready')
        out = svc.predict(self.held)
        direct = 1 - self.predict_target(self.models['bike'], self.held, self.columns, STATIONS)
        np.testing.assert_allclose(out['p_bike_available'].to_numpy(), direct, rtol=1e-9)
        self.assertEqual(set(out['method']), {'lightgbm_sigmoid'})

    def test_corrupted_model_falls_back_to_b2(self):
        from bikeflow_model.forecaster import ForecasterService
        bad = self.tmp / 'bad'
        shutil.copytree(self.tmp / 'model', bad, dirs_exist_ok=True)
        (bad / 'bike_lgbm.txt').write_text('corrupted', encoding='utf-8')
        svc = ForecasterService(bad, rates_table(0.8))
        self.assertEqual(svc.status()['status'], 'degraded')
        out = svc.predict(self.held)
        self.assertEqual(set(out['method']), {'B2_historical'})
        np.testing.assert_allclose(out['p_bike_available'], 0.8)

    def test_stale_input_suppresses_every_method(self):
        from bikeflow_model.forecaster import ForecasterService
        stale = self.held.head(5).copy()
        stale['base_age_seconds'] = 1200.0
        out = ForecasterService(self.tmp / 'model', rates_table()).predict(stale)
        self.assertTrue(out['p_bike_available'].isna().all())
        self.assertEqual(set(out['method']), {'suppressed_stale_input'})

    def test_no_artifacts_reports_unavailable(self):
        from bikeflow_model.forecaster import ForecasterService
        svc = ForecasterService(self.tmp / 'missing', None)
        self.assertEqual(svc.status()['status'], 'unavailable')
        self.assertEqual(set(svc.predict(self.held.head(3))['method']), {'unavailable'})


if __name__ == '__main__':
    unittest.main()
