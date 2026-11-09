"""The Git clone's real serving bundle must work without private data paths."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from backend.artifacts import BUNDLE, BUNDLE_MANIFEST, materialize_bundle, resolve_data_root
from backend.core import Planner
from backend.main import app
from backend.policy import Policy
from backend.providers import Providers, local_time


class BundledArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = materialize_bundle(cache_root=Path(cls.temp.name))
        cls.provider = Providers(cls.root)
        cls.when = local_time('2021-07-20T08:06:00-05:00')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_bundle_is_complete_but_excludes_training_and_final_test_data(self):
        with zipfile.ZipFile(BUNDLE) as archive:
            names = archive.namelist()
        self.assertEqual(len(names), 70)
        self.assertEqual(sum('/features/' in name for name in names), 32)
        self.assertEqual(sum('/labels/' in name for name in names), 32)
        self.assertFalse(any(token in name for name in names for token in ('_train.parquet', '_test.parquet', '_calibration.parquet', 'current_validation/', 'forward_train_predictions')))

    def test_external_override_is_not_replaced_with_the_bundle(self):
        with patch.dict(os.environ, {'BIKEFLOW_DATA_ROOT':'explicit-missing-data'}):
            root, source = resolve_data_root()
        self.assertEqual(root, Path('explicit-missing-data'))
        self.assertEqual(source, 'environment')

    def test_default_resolves_bundle_and_health_distinguishes_real_data(self):
        with patch.dict(os.environ, {'BIKEFLOW_DATA_ROOT':'', 'BIKEFLOW_MOUNTED_DATA_ROOT':''}), patch('backend.artifacts.materialize_bundle', return_value=self.root):
            provider = Providers()
        self.assertEqual(provider.health()['data_source'], 'bundled_m3_tune')
        self.assertEqual(provider.health()['status'], 'ready')
        self.assertTrue(provider.health()['replay_data_ready'])

    def test_real_station_predictions_plan_and_reveal(self):
        with patch.dict(os.environ, {'BIKEFLOW_LIVE':'0'}), patch('backend.main.Providers', return_value=self.provider):
            with TestClient(app) as client:
                response = client.get('/stations',params=dict(mode='replay',historical_timestamp=self.when.isoformat()))
                self.assertEqual(response.status_code,200,response.text)
                snapshot = response.json()
                self.assertEqual(snapshot['active_method'],'lightgbm_sigmoid')
                self.assertEqual(len(snapshot['stations']),32)
                self.assertEqual(snapshot['stations'][0]['bikes'],5)
                for station in snapshot['stations']:
                    self.assertEqual(len(station['forecast']),6)
                request = dict(mode='replay',origin='chicago:14',destination='chicago:21',method='B3',
                               walk_limit_minutes=10,historical_timestamp=self.when.isoformat(),departure_time=self.when.isoformat())
                response = client.post('/plan',json=request)
                self.assertEqual(response.status_code,200,response.text)
                plan = response.json()
                self.assertEqual(plan['actual_method'],'B3')
                self.assertEqual(plan['model_version'],'forecaster_v0_m3')
                self.assertEqual(plan['status'],'ok')
                self.assertFalse(any('SYNTHETIC' in w for w in plan['warnings']))
                attempts = [dict(station_id=plan['primary'][key]['id'],horizon_minutes=plan['primary'][key]['horizon_minutes'],phase=phase)
                            for key,phase in [('pickup','pickup'),('dropoff','return')]]
                response = client.post('/replay/reveal',json=dict(historical_timestamp=plan['decision_time'],attempts=attempts))
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(len(response.json()['outcomes']),2)
                # Final-test dates stay blocked despite full artifacts existing elsewhere.
                request.update(historical_timestamp='2021-08-10T08:06:00-05:00',departure_time='2021-08-10T08:06:00-05:00')
                self.assertEqual(client.post('/plan',json=request).status_code,422)

    def test_corrupt_archive_is_rejected_before_using_cache(self):
        manifest = json.loads(BUNDLE_MANIFEST.read_text(encoding='utf-8'))
        manifest['sha256'] = '0'*64
        path = Path(self.temp.name) / 'bad-manifest.json'
        path.write_text(json.dumps(manifest),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):
            materialize_bundle(manifest_path=path,cache_root=Path(self.temp.name))

    @unittest.skipUnless(Policy.runtime_ready(), 'optional PPO runtime not installed')
    def test_real_ppo_artifact_executes_without_a_greedy_fallback(self):
        snap = self.provider.replay(self.when)
        result = Planner().plan(dict(origin='chicago:14',destination='chicago:21',departure_time=self.when,
                                     method='RL',walk_limit_minutes=10),snap,self.provider.policy)
        self.assertIn(result['actual_method'],('RL_pickup+B3_return','RL_wait+B3_provisional'),result['warnings'])


if __name__ == '__main__':
    unittest.main()
