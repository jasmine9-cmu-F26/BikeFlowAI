"""Measured uptime denominators, missing slots and raw-cloud export integrity."""
from pathlib import Path
import gzip,hashlib,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/data'))
from audit_collector_health import summarize,parse_google


class CollectorHealthTests(unittest.TestCase):
    def test_missing_attempt_is_distinct_from_explicit_failure_and_manual_probe(self):
        def row(t,status='ok',kind='scheduled'):
            return dict(started_epoch=t,received_epoch=t,status=status,invocation=kind,station_count=2,
                feed_age_seconds=5,provider_last_updated=1)
        result=summarize([row(0),row(300,'error'),row(900),row(901,kind='manual')],300,0,1200)
        self.assertEqual(result['expected_poll_slots'],4)
        self.assertEqual(result['successful_polls'],2);self.assertEqual(result['failed_attempts'],1)
        self.assertEqual(result['missing_attempt_slots'],1);self.assertEqual(result['slots_without_success'],2)
        self.assertEqual(result['manual_polls_excluded'],1);self.assertEqual(result['repeated_provider_timestamps'],1)

    def test_small_scheduler_jitter_does_not_create_false_missing_slots(self):
        rows=[dict(started_epoch=t,received_epoch=t,status='ok',invocation='scheduled',station_count=2) for t in [0,299,600]]
        result=summarize(rows,300,0,601)
        self.assertEqual(result['successful_slots'],3);self.assertEqual(result['slots_without_success'],0)

    def test_cloud_export_parser_verifies_raw_hash_instead_of_trusting_success_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw='{"data":{"stations":[{"station_id":"a"},{"station_id":"b"}]}}'
            record=dict(collector='apps-script-v1',started_at_utc='2026-10-30T23:00:00Z',status='ok',invocation='scheduled',station_count=2,
                sources=dict(station_status=dict(raw_json=raw,sha256_utf8=hashlib.sha256(raw.encode()).hexdigest(),received_at_utc='2026-10-30T23:00:01Z')))
            p=root/'poll.json.gz';p.write_bytes(gzip.compress(json.dumps(record).encode()))
            rows,errors=parse_google(root);self.assertEqual(len(rows),1);self.assertFalse(errors)
            record['sources']['station_status']['sha256_utf8']='corrupt';p.write_bytes(gzip.compress(json.dumps(record).encode()))
            rows,errors=parse_google(root);self.assertFalse(rows);self.assertEqual(len(errors),1)


if __name__=='__main__':unittest.main()
