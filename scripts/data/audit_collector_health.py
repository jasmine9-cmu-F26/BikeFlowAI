"""Measure actual capture attempts/gaps from local logs or exported Drive polls.

An expected-slot denominator is explicit; manual duplicates are not uptime.
Google cloud raw data must be exported locally for independent retrospective
metrics; an initial status screenshot alone is not a full uptime audit.
"""
import argparse,gzip,hashlib,json,math
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from pipeline_audit_common import *


def summarize(records,interval_seconds,window_start,window_end):
    if window_end<=window_start:raise ValueError('Health window must have positive duration')
    selected=[r for r in records if window_start<=r['started_epoch']<window_end]
    scheduled=[r for r in selected if r.get('invocation')!='manual']
    expected=math.ceil((window_end-window_start)/interval_seconds)
    # Fixed declared phase; multiple observations in one expected slot count once.
    slot=lambda r:int(math.floor((r['started_epoch']-window_start)/interval_seconds+.5))
    if scheduled:expected=max(expected,max(slot(r) for r in scheduled)+1)
    success=[r for r in scheduled if r['status']=='ok'];failed=[r for r in scheduled if r['status']!='ok']
    successful_slots={slot(r) for r in success};attempted_slots={slot(r) for r in scheduled}
    timestamps=np.sort([r['received_epoch'] for r in success]);diff=np.diff(timestamps)
    boundary=[timestamps[0]-window_start,window_end-timestamps[-1]] if len(timestamps) else [window_end-window_start]
    longest=max([*diff.tolist(),*boundary])
    counts=[r['station_count'] for r in success if r.get('station_count') is not None]
    ages=[r['feed_age_seconds'] for r in success if r.get('feed_age_seconds') is not None]
    provider=[r['provider_last_updated'] for r in success if r.get('provider_last_updated') is not None]
    return dict(window_start_utc=iso(window_start),window_end_utc_exclusive=iso(window_end),nominal_interval_seconds=interval_seconds,
        expected_poll_slots=expected,recorded_attempts=len(scheduled),successful_polls=len(success),failed_attempts=len(failed),
        manual_polls_excluded=sum(r.get('invocation')=='manual' for r in selected),successful_slots=len(successful_slots),
        missing_attempt_slots=expected-len(attempted_slots),slots_without_success=expected-len(successful_slots),
        observed_slot_success_fraction=len(successful_slots)/expected if expected else None,
        extra_attempts_in_occupied_slot=len(scheduled)-len(attempted_slots),
        longest_success_gap_including_boundaries_seconds=float(longest),median_interval_seconds=float(np.median(diff)) if len(diff) else None,
        p90_interval_seconds=float(np.quantile(diff,.9)) if len(diff) else None,duplicate_capture_timestamps=len(timestamps)-len(set(timestamps)),
        repeated_provider_timestamps=len(provider)-len(set(provider)),station_count_min=min(counts) if counts else None,
        station_count_max=max(counts) if counts else None,station_count_median=float(np.median(counts)) if counts else None,
        feed_age_median_seconds=float(np.median(ages)) if ages else None,feed_age_p90_seconds=float(np.quantile(ages,.9)) if ages else None,
        feed_age_max_seconds=max(ages) if ages else None,stale_feed_polls_gt5min=sum(age>300 for age in ages),
        interpretation='Expected slots use a declared window/phase; source timestamp repetition is measured but unchanged polls remain retained; errors/missing triggers never imply empty stations')


def parse_local(root):
    records=[];issues=[]
    for number,line in enumerate((root/'polls.jsonl').read_text(encoding='utf-8').splitlines(),1):
        try:r=json.loads(line)
        except json.JSONDecodeError:issues.append(dict(line=number,error='Malformed JSON log line'));continue
        start=epoch(r['started_at_utc']);status=r['status'];received=epoch(r.get('status_capture',{}).get('received_at_utc',r['started_at_utc']))
        last=r.get('feed_last_updated');verified=False
        if status=='ok':
            p=root/r['snapshot_path']
            if not p.exists():issues.append(dict(line=number,error='Missing raw snapshot'))
            else:
                raw=gzip.decompress(p.read_bytes());verified=hashlib.sha256(raw).hexdigest()==r['status_capture']['sha256']
                if len(json.loads(raw)['data']['stations'])!=r['station_count']:verified=False
                if not verified:issues.append(dict(line=number,error='Raw status hash mismatch'))
        records.append(dict(started_epoch=start,received_epoch=received,status=status,station_count=r.get('station_count'),
            provider_last_updated=last,feed_age_seconds=received-last if isinstance(last,(int,float)) else None,raw_hash_verified=verified,
            invocation='unknown_local_origin'))
    return records,issues


def parse_google(root):
    records=[];issues=[]
    for p in sorted(root.rglob('*.json.gz')):
        try:
            r=json.loads(gzip.decompress(p.read_bytes()))
            if not str(r.get('collector','')).startswith('apps-script'):continue
            received=epoch(r.get('sources',{}).get('station_status',{}).get('received_at_utc',r['started_at_utc']))
            if r['status']=='ok':
                for source in r['sources'].values():
                    if hashlib.sha256(source['raw_json'].encode('utf-8')).hexdigest()!=source['sha256_utf8']:raise ValueError('Raw UTF-8 hash mismatch')
                stations=json.loads(r['sources']['station_status']['raw_json'])['data']['stations']
                if not stations or len(stations)!=r['station_count'] or len({s['station_id'] for s in stations})!=len(stations):raise ValueError('Empty, duplicate or count-mismatched full station response')
            last=r.get('provider_last_updated')
            records.append(dict(started_epoch=epoch(r['started_at_utc']),received_epoch=received,status=r['status'],station_count=r.get('station_count'),
                invocation=r.get('invocation','unknown'),provider_last_updated=last,feed_age_seconds=received-last if isinstance(last,(int,float)) else None,raw_hash_verified=r['status']=='ok'))
        except (ValueError,KeyError,OSError) as exc:issues.append(dict(filename=p.name,error=str(exc)))
    return records,issues


def audit(data_root,reports,google_root=None):
    out=reports/'collector_health';out.mkdir(parents=True,exist_ok=True)
    local=data_root.parent/'current_validation';records,issues=parse_local(local)
    # Installation's scheduled start is known; exclude earlier manual probes.
    installation=read(local/'installation.json');start=epoch(installation['next_run_local'])
    stopped=read(Path(__file__).resolve().parents[2]/'reports/chicago_historical_audit/cloud_collector_handoff.json')['local_task']['verified_at_utc']
    end=epoch(stopped)
    result=summarize(records,120,start,end)
    result.update(source='Retired local collector log and verified raw status files',raw_success_files_verified=sum(r['raw_hash_verified'] for r in records),raw_integrity_issues=issues,
        source_log_sha256=sha(local/'polls.jsonl'),local_task='Disabled',window_basis='Recorded installation next scheduled start through directly verified task-disable time',
        limitation='Local records do not distinguish manual from scheduled origin; extra attempts are exposed and counted only once per expected slot')
    write_json(out/'local_health.json',result)
    if google_root:
        cloud,cloudissues=parse_google(google_root);scheduled=[r for r in cloud if r['invocation']=='scheduled']
        if not scheduled:raise ValueError('No scheduled Google captures found in supplied export')
        # Caller/export audit is bounded to observed interval, not claimed entire
        # deployment uptime. End is now; missing tail is measured explicitly.
        first=min(r['started_epoch'] for r in scheduled);cloudresult=summarize(cloud,300,first,int(datetime.now(timezone.utc).timestamp()))
        cloudresult.update(status='EXPORTED_CLOUD_CAPTURE_WINDOW_AUDITED',window_basis='First scheduled poll present in export through audit time; excludes pre-export prefix',integrity_issues=cloudissues)
    else:
        cloudresult=dict(status='PENDING_CLOUD_EXPORT_OR_HEALTH_INDEX_UPDATE',cloud_uptime_measured=False,
            initial_handoff='User supplied successful scheduled logs; this does not independently quantify continuous uptime',
            active_cloud_version_verified='apps-script-v1',nominal_interval_seconds=300,
            next='Update prepared Code.gs in existing Google project to enable rolling health metadata; run collectorHealth after new scheduled polls, or export Drive folder and use --google-root',
            no_cloud_raw_access_available=True,no_local_task_reenabled=True)
    write_json(out/'google_health.json',cloudresult)
    write_json(out/'audit_summary.json',dict(local_health_complete=True,cloud_health_status=cloudresult['status'],
        cloud_uptime_claim_allowed=bool(google_root),script_sha256=sha(Path(__file__)),metric_semantics='Attempts/errors and missing expected slots are separate; duplicate provider timestamps are not suppressed'))
    print(json.dumps(dict(local_successful_polls=result['successful_polls'],local_expected_slots=result['expected_poll_slots'],cloud_health=cloudresult['status']),indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-root',type=Path,required=True);p.add_argument('--google-root',type=Path);p.add_argument('--reports',type=Path,default=Path('reports/final_pipeline_audit'))
    args=p.parse_args();audit(args.data_root,args.reports,args.google_root)


if __name__=='__main__':main()
