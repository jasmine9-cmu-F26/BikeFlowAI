"""Offline full-GBFS poll, error heartbeat and process-lock tests."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/data'))
import collect_divvy_gbfs as collector


class CollectorTests(unittest.TestCase):
    def fake_fetch(self,url):
        if url.endswith('gbfs.json'):
            data=dict(data={'en':{'feeds':[dict(name=n,url='https://gbfs.lyft.com/'+n+'.json') for n in ['station_information','station_status','system_information']]}})
        elif 'station_information' in url:data=dict(data=dict(stations=[dict(station_id='synthetic-long-12345678901234567890',name='Synthetic A',lat=41.88,lon=-87.64,capacity=10)]))
        elif 'station_status' in url:data=dict(last_updated=int(time.time()),ttl=60,version='2.3',data=dict(stations=[dict(station_id='synthetic-long-12345678901234567890',num_bikes_available=2,num_docks_available=8)]))
        else:data=dict(data=dict(timezone='America/Chicago'))
        raw=json.dumps(data).encode();stamp=datetime.now(timezone.utc).isoformat()
        return data,raw,dict(url=url,requested_at_utc=stamp,received_at_utc=stamp,sha256=hashlib.sha256(raw).hexdigest())

    def test_identical_inventory_is_saved_as_two_full_heartbeats(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(collector,'fetch',side_effect=self.fake_fetch):
            a=collector.capture(tmp);b=collector.capture(tmp)
            root=Path(tmp)/'current_validation'
            self.assertEqual((a['status'],b['status']),('ok','ok'))
            self.assertNotEqual(a['snapshot_path'],b['snapshot_path'])
            self.assertEqual(len(list((root/'status').rglob('*.json.gz'))),2)
            self.assertEqual(len(list((root/'metadata').glob('*.json.gz'))),1)
            self.assertFalse(b['unchanged_inventory_suppressed'])
            self.assertEqual(len((root/'polls.jsonl').read_text().splitlines()),2)

    def test_network_failure_is_not_an_empty_station_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(collector,'fetch',side_effect=OSError('synthetic offline')):
            result=collector.capture(tmp);root=Path(tmp)/'current_validation'
            self.assertEqual(result['status'],'error');self.assertNotIn('snapshot_path',result)
            self.assertFalse((root/'status').exists())
            self.assertEqual(json.loads((root/'state.json').read_text())['failed_polls'],1)

    def test_capture_lock_releases_and_prevents_overlapping_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with collector.capture_lock(root) as first:
                self.assertTrue(first)
                with collector.capture_lock(root) as second:self.assertFalse(second)
            with collector.capture_lock(root) as third:self.assertTrue(third)

if __name__=='__main__':unittest.main()
