"""Application contract / failure tests. No network, weights or raw data required."""
import copy
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['BIKEFLOW_LIVE'] = '0'

from fastapi.testclient import TestClient
from backend.core import Planner, horizon
from backend.main import app
from backend.policy import Policy, observation
from backend.providers import Providers, local_time

BASE = dict(mode='fixture', origin='chicago:14', destination='chicago:21',
            departure_time='2021-07-20T08:00:00-05:00', historical_timestamp='2021-07-20T08:00:00-05:00',
            walk_limit_minutes=10, method='B3')


class AppAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def post(self, **changes):
        return self.client.post('/plan', json={**BASE, **changes})

    def test_complete_plan_and_supported_horizons(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        p = r.json()
        self.assertEqual(p['status'], 'ok')
        self.assertEqual(p['mode'], 'fixture')
        self.assertEqual(p['primary']['pickup']['id'], 'chicago:15')
        self.assertTrue(any('SYNTHETIC' in w for w in p['warnings']))
        self.assertLessEqual(p['primary']['wait_minutes'], 20)
        for route in [p['primary'], *p['backups']]:
            for phase in ('pickup', 'dropoff'):
                stop = route[phase]
                self.assertIn(stop['horizon_minutes'], [10, 20, 30, 40, 50, 60])
                self.assertLessEqual(stop['walk_minutes'], 10)
                self.assertGreaterEqual(local_time(stop['effective_prediction_time']), local_time(stop['estimated_arrival_time']))

    def test_stale_suppresses_even_b1_and_b2(self):
        for method in ('B1', 'B2', 'B3', 'RL'):
            p = self.post(scenario='stale', method=method).json()
            self.assertEqual(p['status'], 'no_plan')
            self.assertIsNone(p['primary'])
        s = self.client.get('/stations', params=dict(mode='fixture', historical_timestamp=BASE['historical_timestamp'], scenario='stale')).json()
        self.assertTrue(s['stations'])
        self.assertTrue(all(not st['forecast'] and not st['b2'] for st in s['stations']))

    def test_model_fallback_is_explicit(self):
        p = self.post(scenario='model-missing').json()
        self.assertEqual(p['actual_method'], 'B2')
        self.assertEqual(p['primary']['pickup']['probability'], .72)
        rl = self.post(method='RL').json()
        self.assertEqual(rl['actual_method'], 'B3')
        self.assertTrue(any('RL unavailable' in w for w in rl['warnings']))

    def test_invalid_inputs_never_call_provider(self):
        cases = [dict(walk_limit_minutes=-1), dict(origin='unknown'), dict(destination=BASE['origin']),
                 dict(origin={'lat':0,'lon':0}), dict(origin={'lat':100,'lon':0}),
                 dict(departure_time='2021-07-20T07:59:00-05:00'), dict(historical_timestamp=None),
                 dict(departure_time='2021-07-20T09:01:00-05:00'), dict(mode='unknown')]
        with patch.object(app.state.providers, 'snapshot', side_effect=AssertionError('inference before validation')):
            for values in cases:
                with self.subTest(values=values):
                    r = self.post(**values)
                    self.assertEqual(r.status_code, 422, r.text)
                    self.assertNotIn('"input"', r.text)

    def test_live_clock_and_replay_clock_are_separate(self):
        self.assertEqual(self.post(mode='live').status_code, 422)
        self.assertEqual(self.post().status_code, 200)

    def test_failure_replans_exclude_tried_station(self):
        first = self.post().json()['primary']
        for phase, stop in [('pickup',first['pickup']), ('return',first['dropoff'])]:
            r = self.client.post('/replan', json={**BASE, 'origin':stop['id'], 'departure_time':stop['estimated_arrival_time'],
                                                'historical_timestamp':stop['estimated_arrival_time'], 'phase':phase,
                                                'failed_station_ids':[stop['id']]})
            self.assertEqual(r.status_code, 200, r.text)
            p = r.json()
            if p['status'] == 'ok':
                key = 'pickup' if phase == 'pickup' else 'dropoff'
                self.assertNotEqual(p['primary'][key]['id'], stop['id'])
                if phase == 'return':
                    self.assertIsNone(p['primary']['pickup'])

    def test_registry_available_without_data(self):
        self.assertEqual(len(self.client.get('/registry').json()['stations']), 32)

    def test_missing_real_data_not_replaced_by_examples(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(app.state.providers, 'root', Path(d)):
                r = self.post(mode='replay')
                self.assertEqual(r.status_code, 422)
                self.assertIn('Replay data not prepared', r.text)

    def test_log_does_not_include_locations_or_raw_inputs(self):
        with self.assertLogs('bikeflow.requests', level=logging.INFO) as logs:
            self.post(origin={'lat':41.858086,'lon':-87.651073})
        output = '\n'.join(logs.output)
        self.assertNotIn('41.858086', output)
        self.assertNotIn('87.651073', output)
        self.assertNotIn('historical_timestamp', output)
        self.assertIn('request_id', output)

    def test_closed_and_stale_stations_are_excluded(self):
        provider = app.state.providers
        snap = provider.fixture(local_time(BASE['historical_timestamp']), 'normal')
        for s in snap['stations']:
            if s['id'] == 'chicago:15':
                s['pickup'] = False
        with patch.object(provider, 'snapshot', return_value=snap):
            p = self.post().json()
            self.assertNotEqual(p['primary']['pickup']['id'], 'chicago:15')

    def test_b1_does_not_send_rider_to_known_empty_pickup(self):
        provider = app.state.providers
        snap = provider.fixture(local_time(BASE['historical_timestamp']), 'normal')
        for st in snap['stations']:
            st['bikes'] = 0
        with patch.object(provider, 'snapshot', return_value=snap):
            p = self.post(method='B1').json()
            self.assertEqual(p['status'], 'no_plan')


class PolicyBridge(unittest.TestCase):
    def test_vector_and_masks_match_training_layout(self):
        slot = dict(valid=True,walk_minutes=5,horizon=20,share=.25,empty_now=False,p_fail=.2,p_next=.3,p_b2=.4)
        obs, mask = observation([slot], phase='return', waits=1, elapsed_minutes=15, failures=2)
        self.assertEqual(len(obs),31)
        self.assertEqual(obs[:9],[1.,.5,1/3,.25,0.,.2,.3,.4,0.])
        self.assertEqual(obs[-4:],[1.,.5,.25,2/3])
        self.assertEqual(mask,[True,False,False,False])

    def test_missing_artifact_and_forbidden_action(self):
        with tempfile.TemporaryDirectory() as d:
            p = Policy(Path(d))
            with self.assertRaises(ValueError):
                p.choose([],10)
            p.path.parent.mkdir(parents=True)
            p.path.write_bytes(b'test')
            p.manifest.write_text(json.dumps(dict(observation_size=31,walk_limit_minutes=10,lam=.02,mu=.01,c=.5)))
            with patch('backend.policy.subprocess.run') as run:
                run.return_value.returncode=0
                run.return_value.stdout='{"action": 2}'
                slot = dict(valid=True,walk_minutes=0,horizon=10,share=.5,empty_now=False,p_fail=.1,p_next=.1,p_b2=.1)
                with self.assertRaisesRegex(ValueError,'forbidden'):
                    p.choose([slot],10)
                with self.assertRaisesRegex(ValueError,'configuration'):
                    p.choose([slot],5)


if __name__ == '__main__':
    unittest.main()
