"""Offline AWS persistence, idempotency, failure and deployment-code checks."""
from datetime import datetime,timezone,timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/data'))
sys.path.insert(0,str(ROOT/'deploy/aws_collector'))
import handler
import manage_collector
from build_template import template
import test_gbfs_collector as gbfs_tests


class S3Error(Exception):
    def __init__(self,code):self.response={'Error':{'Code':code}}


class FakeS3:
    def __init__(self):self.objects={};self.fail_status=False
    def put_object(self,**args):
        key=args['Key']
        if self.fail_status and '/status/' in key:raise OSError('synthetic S3 upload outage')
        if args.get('IfNoneMatch')=='*' and key in self.objects:raise S3Error('PreconditionFailed')
        self.objects[key]=args
    def head_object(self,**args):
        value=self.objects[args['Key']]
        return dict(ContentLength=len(value['Body']),Metadata=value['Metadata'])


class AWSCollectorTests(unittest.TestCase):
    def setUp(self):
        self.s3=FakeS3();self.context=types.SimpleNamespace(aws_request_id='synthetic-1')
        self.stop=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        base=gbfs_tests.CollectorTests().fake_fetch
        self.info_count=0
        def fetch(url):
            document,body,meta=base(url)
            if 'station_information' in url:
                self.info_count+=1;document['last_updated']=self.info_count
                body=json.dumps(document).encode();meta['sha256']=hashlib.sha256(body).hexdigest()
            return document,body,meta
        self.fetch=fetch
    def records(self):
        return [json.loads(v['Body']) for k,v in self.s3.objects.items() if '/polls/' in k]

    def test_same_inventory_keeps_two_polls_and_stored_hashes_match(self):
        with patch.object(handler.collector,'fetch',side_effect=self.fetch):
            handler.run({},self.context,self.s3,'private-test',self.stop)
            self.context.aws_request_id='synthetic-2'
            handler.run({},self.context,self.s3,'private-test',self.stop)
        records=self.records();self.assertEqual(len(records),2)
        self.assertEqual(len([k for k in self.s3.objects if '/status/' in k]),2)
        self.assertEqual(len([k for k in self.s3.objects if '/metadata/' in k]),1)
        for record in records:
            self.assertEqual(record['status'],'ok');self.assertFalse(record['unchanged_inventory_suppressed'])
            for item in record['uploaded_objects']:
                self.assertEqual(hashlib.sha256(self.s3.objects[item['key']]['Body']).hexdigest(),item['sha256'])

    def test_duplicate_scheduled_slot_cannot_capture_twice(self):
        event=dict(scheduled_time=datetime.now(timezone.utc).isoformat())
        with patch.object(handler.collector,'fetch',side_effect=self.fetch) as fetch:
            self.assertEqual(handler.run(event,self.context,self.s3,'private-test',self.stop)['status'],'ok')
            count=fetch.call_count
            self.assertEqual(handler.run(event,self.context,self.s3,'private-test',self.stop)['status'],'duplicate_slot_skipped')
            self.assertEqual(fetch.call_count,count)

    def test_network_failure_is_a_persisted_error_and_lambda_failure(self):
        with patch.object(handler.collector,'fetch',side_effect=OSError('synthetic offline')):
            with self.assertRaises(RuntimeError):handler.run({},self.context,self.s3,'private-test',self.stop)
        self.assertEqual(self.records()[0]['status'],'error')
        self.assertFalse(any('/status/' in k for k in self.s3.objects))

    def test_storage_failure_never_publishes_success(self):
        self.s3.fail_status=True
        with patch.object(handler.collector,'fetch',side_effect=self.fetch):
            with self.assertRaises(OSError):handler.run({},self.context,self.s3,'private-test',self.stop)
        self.assertTrue(all(r['status']=='error' for r in self.records()))

    def test_expired_and_delayed_slots_do_not_backfill(self):
        past=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        self.assertEqual(handler.run({},self.context,self.s3,'private-test',past)['status'],'finished')
        self.assertFalse(self.s3.objects)
        with patch.object(handler.collector,'capture') as capture:
            with self.assertRaises(RuntimeError):handler.run(dict(scheduled_time=past),self.context,self.s3,'private-test',self.stop)
            capture.assert_not_called()
        self.assertEqual(self.records()[0]['status'],'error')

    def test_template_private_storage_off_by_default_and_no_server(self):
        result=json.loads((ROOT/'deploy/aws_collector/template.json').read_text())
        self.assertEqual(result['Parameters']['ScheduleState']['Default'],'DISABLED')
        resources=result['Resources'];bucket=resources['DataBucket']
        self.assertTrue(all(bucket['Properties']['PublicAccessBlockConfiguration'].values()))
        self.assertEqual(bucket['DeletionPolicy'],'Retain')
        self.assertEqual(resources['CollectorFunction']['Properties']['Runtime'],'python3.14')
        self.assertNotIn('ReservedConcurrentExecutions',resources['CollectorFunction']['Properties'])
        self.assertEqual(resources['CollectionSchedule']['Properties']['ScheduleExpression'],'rate(2 minutes)')
        self.assertFalse(any(r['Type'].startswith(('AWS::EC2','AWS::ApiGateway')) for r in resources.values()))

    def test_self_contained_inline_lambda_runs_offline(self):
        code=json.loads((ROOT/'deploy/aws_collector/template.json').read_text())['Resources']['CollectorFunction']['Properties']['Code']['ZipFile']
        module=types.ModuleType('bikeflow_inline_test')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index.py';path.write_text(code,encoding='utf-8',newline='\n');module.__file__=str(path)
            with patch.dict(sys.modules,{'bikeflow_inline_test':module}):
                exec(compile(code,str(path),'exec'),module.__dict__)
                with patch.object(module,'fetch',side_effect=self.fetch):
                    result=module.run({},self.context,self.s3,'private-test',self.stop)
            self.assertEqual(result['status'],'ok')
            self.assertEqual(self.records()[0]['collector_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())

    def test_migration_verify_rejects_manual_only_evidence(self):
        with patch.object(manage_collector,'outputs',return_value=({},dict(ScheduleState='ENABLED',DataBucketName='private-test',ScheduleName='test',ScheduleGroupName='test'))), \
             patch.object(manage_collector,'cli',side_effect=[dict(State='ENABLED',ScheduleExpression='rate(2 minutes)'),dict(PublicAccessBlockConfiguration=dict(BlockPublicAcls=True))]), \
             patch.object(manage_collector,'recent_records',return_value=[dict(status='ok',scheduled_time=None)]):
            with self.assertRaisesRegex(RuntimeError,'two distinct'):manage_collector.verify('us-east-1','synthetic')

    def test_cli_accepts_successful_cloudformation_progress_text(self):
        result=types.SimpleNamespace(returncode=0,stdout='Successfully created stack\n',stderr='')
        with patch.object(manage_collector.subprocess,'run',return_value=result):
            self.assertIn('Successfully',manage_collector.cli('us-east-1','cloudformation','deploy')['message'])


if __name__=='__main__':unittest.main()
