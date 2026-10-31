"""Stateless AWS adapter: immutable full polls in a private S3 bucket.

No shared mutable state, public endpoint, cross-account keys or local disk
dependency. A conditional slot claim prevents duplicate scheduled captures.
"""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import collect_divvy_gbfs as collector


def utc_time():return datetime.now(timezone.utc)


def error_code(exc):
    return getattr(exc,'response',{}).get('Error',{}).get('Code')


def put_bytes(s3,bucket,key,body,immutable=False,content_type='application/json'):
    args=dict(Bucket=bucket,Key=key,Body=body,ContentType=content_type,
        ServerSideEncryption='AES256',Metadata={'sha256':hashlib.sha256(body).hexdigest()})
    if immutable:args['IfNoneMatch']='*'
    try:s3.put_object(**args);return True
    except Exception as exc:
        if immutable and error_code(exc) in {'PreconditionFailed','412'}:return False
        raise


def run(event,context,s3,bucket,stop_at):
    now_utc=utc_time()
    if now_utc>=datetime.fromisoformat(stop_at.replace('Z','+00:00')):
        return dict(status='finished',reason='Configured collection end reached')
    scheduled=event.get('scheduled_time')
    if scheduled:
        slot=datetime.fromisoformat(scheduled.replace('Z','+00:00'))
        if slot.tzinfo is None:raise ValueError('Scheduled time needs an explicit timezone')
        slot=slot.astimezone(timezone.utc)
        token=slot.isoformat()
    else:
        slot=now_utc;token='manual:'+context.aws_request_id
    run_id=hashlib.sha256(token.encode()).hexdigest()[:24]
    date=f'{slot:%Y/%m/%d}'
    prefix='current_validation/'
    claim_key=prefix+f'claims/{date}/{run_id}.json'
    record_key=prefix+f'polls/{date}/{run_id}.json'
    claim=dict(scheduled_time=scheduled,aws_request_id=context.aws_request_id,claimed_at_utc=now_utc.isoformat())
    if not put_bytes(s3,bucket,claim_key,json.dumps(claim).encode(),immutable=True):
        # An incomplete claim is deliberately not overwritten/retried into a
        # backdated observation. CloudWatch errors and missing manifests expose
        # crashes/storage failures; a later regular slot is independent.
        return dict(status='duplicate_slot_skipped',claim_key=claim_key)
    record=dict(deployment='aws_lambda',aws_request_id=context.aws_request_id,scheduled_time=scheduled,
        actual_invocation_utc=now_utc.isoformat(),collector_base_sha256=os.environ.get('COLLECTOR_BASE_SHA256'),
        snapshot_timing='Actual provider/request/receipt times; never pretend a delayed poll occurred at scheduled time')
    if scheduled and not -60<=(now_utc-slot).total_seconds()<=90:
        record.update(status='error',error='Scheduled slot is too old or in the future; no historical backfill')
        put_bytes(s3,bucket,record_key,json.dumps(record).encode(),immutable=True)
        raise RuntimeError(record['error'])
    try:
        with tempfile.TemporaryDirectory(prefix='bikeflow-') as temp:
            local=Path(temp)/'current_validation'
            captured=collector.capture(temp,stop_at)
            record.update(captured)
            objects=[]
            # Stateless invocation: rediscover official feeds and metadata each
            # poll. The S3 canonical metadata object is content-deduplicated,
            # while every complete status/discovery poll remains immutable.
            for path in sorted(local.rglob('*.json.gz')):
                relative=path.relative_to(local).as_posix();body=path.read_bytes()
                if relative=='system_information.json.gz':
                    relative='system_information/'+hashlib.sha256(body).hexdigest()+'.json.gz'
                key=prefix+relative
                created=put_bytes(s3,bucket,key,body,immutable=True,content_type='application/gzip')
                item=dict(key=key,sha256=hashlib.sha256(body).hexdigest(),bytes=len(body),created=created)
                if not created:
                    # Canonical station metadata may have the same content but
                    # different top-level provider timestamps. Record the hash
                    # of bytes actually stored, alongside this poll's raw hash.
                    existing=s3.head_object(Bucket=bucket,Key=key)
                    item.update(captured_sha256=item['sha256'],sha256=existing['Metadata']['sha256'],bytes=existing['ContentLength'])
                objects.append(item)
            record['uploaded_objects']=objects
            record['cloud_log_layout']='Immutable polls/date/slot.json; no shared polls.jsonl or state.json'
            # Publish the manifest only after all referenced raw objects exist.
            put_bytes(s3,bucket,record_key,json.dumps(record).encode(),immutable=True)
            if record['status']!='ok':raise RuntimeError(record.get('error','Capture failed'))
            print(json.dumps(dict(status='ok',manifest_key=record_key,station_count=record['station_count'])))
            return dict(status='ok',bucket=bucket,manifest_key=record_key,station_count=record['station_count'])
    except Exception as exc:
        if record.get('status')!='error':
            record.update(status='error',error=f'{type(exc).__name__}: {exc}')
            try:put_bytes(s3,bucket,record_key,json.dumps(record).encode(),immutable=True)
            except Exception:pass  # Storage outage is still a Lambda error.
        raise


def lambda_handler(event,context):
    import boto3  # AWS managed runtime SDK; version is managed by AWS.
    return run(event or {},context,boto3.client('s3'),os.environ['DATA_BUCKET'],os.environ['STOP_AT_UTC'])
