"""Run in authenticated AWS CloudShell; passwords/keys never go in this repo.

Creates only this collector's stack. Initial deployment leaves the schedule
disabled. Start smoke-tests the function, then enables the schedule. Verify
requires two recent scheduled captures before local collection is stopped.
"""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def cli(region,*args):
    command=['aws','--region',region,'--no-cli-pager',*args,'--output','json']
    result=subprocess.run(command,capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr.strip())
    if not result.stdout.strip():return {}
    try:return json.loads(result.stdout)
    except json.JSONDecodeError:
        if args[:2]==('cloudformation','deploy'):return dict(message=result.stdout.strip())
        raise


def outputs(region,stack):
    value=cli(region,'cloudformation','describe-stacks','--stack-name',stack)['Stacks'][0]
    return value,{x['OutputKey']:x['OutputValue'] for x in value['Outputs']}


def set_schedule(region,stack,state):
    value,out=outputs(region,stack)
    if out['ScheduleState']==state:return out
    parameters=[dict(ParameterKey=p['ParameterKey'],UsePreviousValue=True) for p in value['Parameters'] if p['ParameterKey']!='ScheduleState']
    parameters.append(dict(ParameterKey='ScheduleState',ParameterValue=state))
    cli(region,'cloudformation','update-stack','--stack-name',stack,'--use-previous-template','--capabilities','CAPABILITY_IAM','--parameters',json.dumps(parameters))
    cli(region,'cloudformation','wait','stack-update-complete','--stack-name',stack)
    return outputs(region,stack)[1]


def get_record(region,bucket,key):
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'record.json'
        cli(region,'s3api','get-object','--bucket',bucket,'--key',key,str(path))
        return json.loads(path.read_text())


def recent_records(region,bucket):
    found=[];now=datetime.now(timezone.utc)
    for day in [now,now-timedelta(days=1)]:
        result=cli(region,'s3api','list-objects-v2','--bucket',bucket,'--prefix',f'current_validation/polls/{day:%Y/%m/%d}/')
        found.extend(result.get('Contents',[]))
    found.sort(key=lambda x:x['LastModified'],reverse=True)
    return [get_record(region,bucket,x['Key']) for x in found[:8]]


def verify(region,stack):
    value,out=outputs(region,stack)
    if out['ScheduleState']!='ENABLED':raise RuntimeError('Cloud schedule is not enabled')
    schedule=cli(region,'scheduler','get-schedule','--name',out['ScheduleName'],'--group-name',out['ScheduleGroupName'])
    if schedule['State']!='ENABLED' or schedule['ScheduleExpression']!='rate(2 minutes)':raise RuntimeError('Actual cloud schedule differs from enabled two-minute configuration')
    bucket=out['DataBucketName']
    access=cli(region,'s3api','get-public-access-block','--bucket',bucket)['PublicAccessBlockConfiguration']
    if not all(access.values()):raise RuntimeError('Bucket public-access block is not fully enabled')
    now=datetime.now(timezone.utc);good=[]
    for record in recent_records(region,bucket):
        if record.get('status')!='ok' or not record.get('scheduled_time') or record.get('stale_feed_over_5min'):continue
        received=datetime.fromisoformat(record['status_capture']['received_at_utc'].replace('Z','+00:00'))
        if not 0<=(now-received).total_seconds()<=360:continue
        expected='current_validation/'+record['snapshot_path']
        item=next((o for o in record['uploaded_objects'] if o['key']==expected),None)
        if not item:continue
        head=cli(region,'s3api','head-object','--bucket',bucket,'--key',expected)
        if head['Metadata']['sha256']!=item['sha256']:raise RuntimeError('Stored snapshot hash mismatch')
        with tempfile.TemporaryDirectory() as temp:
            downloaded=Path(temp)/'snapshot.json.gz'
            cli(region,'s3api','get-object','--bucket',bucket,'--key',expected,str(downloaded))
            if hashlib.sha256(downloaded.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Downloaded snapshot bytes do not match manifest')
        good.append(record)
    slots={r['scheduled_time'] for r in good}
    if len(slots)<2:raise RuntimeError('Need two distinct successful scheduled polls in the last six minutes. Wait 2-4 minutes and rerun verify; keep local collection enabled.')
    latest=max(good,key=lambda r:r['status_capture']['received_at_utc'])
    evidence=dict(verified_at_utc=now.isoformat(),region=region,stack=stack,bucket=bucket,function=out['FunctionName'],
        cloud_schedule='ENABLED',interval_seconds=120,scheduled_slots_verified=sorted(slots),latest_success_utc=latest['status_capture']['received_at_utc'],
        station_count=latest['station_count'],bucket_public_access_blocked=True,raw_snapshot_sha256_verified=True,
        local_collector_disabled=False,stop_at_utc=out['StopAtUtc'])
    Path('cloud_handoff_evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','deploy','start','status','verify','stop'])
    parser.add_argument('--region',default='us-east-1')
    parser.add_argument('--stack',default='bikeflow-divvy-collector')
    parser.add_argument('--confirm-create-resources',action='store_true')
    args=parser.parse_args();region=args.region;stack=args.stack
    template_path=Path(__file__).parent/'template.json'
    if args.action=='plan':
        print(json.dumps(dict(region=region,stack=stack,resources=['private retained S3 bucket','Python 3.14 Lambda, 512MB, timeout 90s','two scoped IAM execution roles','14-day CloudWatch logs','two-minute Scheduler, initially DISABLED'],
            expected_monthly_invocations=21600,estimated_USD_month='1-3 under stated workload assumptions, not a cap or guarantee',no_EC2_NAT_or_public_endpoint=True),indent=2));return
    if args.action=='deploy':
        if not args.confirm_create_resources:parser.error('Review plan and source terms, then pass --confirm-create-resources to create billable AWS resources and scoped IAM roles')
        caller=cli(region,'sts','get-caller-identity')
        try:outputs(region,stack)
        except RuntimeError as error:
            if 'does not exist' not in str(error):raise
        else:raise RuntimeError('Stack already exists; use status/start. This command never silently replaces another stack.')
        cli(region,'cloudformation','validate-template','--template-body','file://'+str(template_path.resolve()))
        cli(region,'cloudformation','deploy','--stack-name',stack,'--template-file',str(template_path.resolve()),'--capabilities','CAPABILITY_IAM',
            '--parameter-overrides','ScheduleState=DISABLED','--tags','Project=BikeFlowAI','Purpose=DivvySnapshotCollection')
        print(json.dumps(dict(account=caller['Account'],outputs=outputs(region,stack)[1],next='Run start to smoke-test and enable cloud schedule'),indent=2));return
    if args.action=='start':
        out=outputs(region,stack)[1]
        with tempfile.TemporaryDirectory() as temp:
            response=Path(temp)/'response.json'
            invocation=cli(region,'lambda','invoke','--function-name',out['FunctionName'],'--cli-binary-format','raw-in-base64-out','--payload','{}',str(response))
            body=json.loads(response.read_text())
            if invocation.get('FunctionError') or body.get('status')!='ok':raise RuntimeError('Cloud smoke capture failed: '+json.dumps(body))
            record=get_record(region,out['DataBucketName'],body['manifest_key'])
            if record.get('status')!='ok' or not record.get('uploaded_objects'):raise RuntimeError('No successful persisted cloud smoke manifest')
        out=set_schedule(region,stack,'ENABLED')
        print(json.dumps(dict(schedule=out['ScheduleState'],smoke_capture=body,next='Wait 2-4 minutes, then run verify. Do not stop local collector until verify passes.'),indent=2));return
    if args.action=='status':
        out=outputs(region,stack)[1]
        records=recent_records(region,out['DataBucketName'])
        print(json.dumps(dict(outputs=out,recent_polls=[dict(status=r.get('status'),scheduled_time=r.get('scheduled_time'),received_at=r.get('status_capture',{}).get('received_at_utc'),station_count=r.get('station_count'),error=r.get('error')) for r in records]),indent=2));return
    if args.action=='verify':print(json.dumps(verify(region,stack),indent=2));return
    if args.action=='stop':
        print(json.dumps(dict(outputs=set_schedule(region,stack,'DISABLED'),data='Retained privately; storage billing continues until explicitly removed'),indent=2))


if __name__=='__main__':main()
