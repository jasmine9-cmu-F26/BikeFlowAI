"""Final app32 trip mapping, planner OD fallback and replay freshness audit."""
import argparse,bisect,csv,hashlib,io,json
from datetime import datetime
from pathlib import Path
import zipfile
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from audit_chicago_trips import endpoint_match,utc_epoch,observable
from bikeflow_data.temporal import norm_name
from pipeline_audit_common import *


def write_weekly_od(normalized,planner,train,target,out):
    """Training replay gets past complete-week OD fits, never final-train fit."""
    history=[r for r in normalized if r['train_OD_eligible']];allrows=[];fitrows=[]
    for week in range(10):
        cutoff=train['lo']+week*7*86400;groups={};used=[]
        for r in history:
            if train['lo']<=r['request_time']<cutoff and train['lo']<=r['return_time']<cutoff:
                groups.setdefault((r['start_station_id'],r['end_station_id']),[]).append(r['duration_seconds']);used.append(r)
        for row in planner:
            values=groups.get((row['start_station_id'],row['end_station_id']),[]);n=len(values)
            allrows.append(dict(row,training_trips=n,observed_in_training=n>0,meets_20_trip_rule=n>=20,
                method='training_median' if n>=20 else 'geometric_fallback_runtime_coordinates',ride_seconds=float(np.median(values)) if n>=20 else None,
                straight_line_m=None,self_pair=str(row['self_pair']).lower()=='true',
                fallback_geometry_policy='Compute 1.3 * distance /4 using metadata as-of each request; never use final-training median coordinates in earlier training replay',
                fit_cutoff_utc=iso(cutoff),version=f'train_week_{week}'))
        fitrows.append(dict(version=f'train_week_{week}',fit_cutoff_utc=iso(cutoff),training_rides=len(used),
            source_max_trip_end_utc=iso(max(r['return_time'] for r in used)) if used else '',
            source_min_trip_start_utc=iso(min(r['request_time'] for r in used)) if used else '',
            use='Only this training week; first week geometric fallback only'))
    output=target/'OD';output.mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(allrows),output/'training_expanding_week_od.parquet',compression='zstd')
    write_csv(out/'OD_training_week_fit_manifest.csv',fitrows)
    return fitrows


def audit(project,data_root,reports):
    protocol=read(project/'data/manifests/chicago/app32/data_protocol.json');scopes=splits(protocol)
    cohort=csvrows(project/protocol['cohort_manifest']);selected={r['station_id'] for r in cohort}
    manifest=read(data_root/'download_manifest.json');lo=scopes[0]['lo'];hi=scopes[-1]['hi'];train=scopes[0]
    mapping={}
    for r in csvrows(project/'data/manifests/chicago/app32/station_id_map.csv'):
        if r['station_id'] not in selected:continue
        r.update(lo=epoch(r['first_observed_utc']),hi=epoch(r['interval_end_utc_exclusive']),lat=float(r['lat']),lon=float(r['lon']))
        mapping.setdefault(r['name_norm'],[]).append(r)
    con=duckdb.connect()
    con.execute('CREATE TEMP TABLE ids(station_id VARCHAR)');con.executemany('INSERT INTO ids VALUES (?)',[(x,) for x in selected])
    table=con.sql('SELECT s.station_id,timestamp,is_in_service FROM read_parquet(?) s JOIN ids USING(station_id) WHERE num_bikes_available>=0 AND num_docks_available>=0 AND is_in_service IS NOT NULL ORDER BY station_id,timestamp',params=[str(data_root/'processed/snapshots.parquet')]).to_arrow_table()
    observed={};flags={}
    for r in table.to_pylist():observed.setdefault(r['station_id'],[]).append(r['timestamp']);flags.setdefault(r['station_id'],[]).append(r['is_in_service'])
    con.close()
    oldod=csvrows(project/'reports/chicago_historical_audit/app32/od_ride_times.csv')
    supports={(r['start_station_id'],r['end_station_id']):r for r in oldod}
    planner=[]
    for a in cohort:
        for b in cohort:
            pair=(a['station_id'],b['station_id']);r=supports.get(pair);n=int(r['training_trips']) if r else 0
            distance=haversine_m(float(a['historical_lat']),float(a['historical_lon']),float(b['historical_lat']),float(b['historical_lon']))
            planner.append(dict(start_station_id=pair[0],end_station_id=pair[1],training_trips=n,observed_in_training=n>0,meets_20_trip_rule=n>=20,
                method='training_median' if n>=20 else 'geometric_fallback',ride_seconds=float(r['median_seconds']) if n>=20 else 1.3*distance/4,
                straight_line_m=distance,self_pair=pair[0]==pair[1],fit_cutoff_utc=iso(train['hi']),source='training-only OD summary, checked against streamed raw trips'))
    counters=dict(raw_rows=0,named_app32_endpoints=0,mapped_app32_trips=0,eligible_training_rides=0,both_endpoints_outcome_observable=0)
    fallback={};fresh={};cache={};normalized=[];training_od={}
    target=data_root/'processed/final_pipeline_v1';target.mkdir(parents=True,exist_ok=True)
    for src in manifest['files']:
        if src['kind']!='trips':continue
        if sha(data_root/src['path'])!=src['sha256']:raise ValueError('Trip ZIP hash mismatch')
        with zipfile.ZipFile(data_root/src['path']) as archive:
            for name in archive.namelist():
                if not name.endswith('.csv') or name.startswith('__MACOSX/'):continue
                with archive.open(name) as binary:
                    for r in csv.DictReader(io.TextIOWrapper(binary,encoding='utf-8-sig')):
                        counters['raw_rows']+=1
                        try:ss,start=utc_epoch(datetime.fromisoformat(r['started_at']),cache);es,end=utc_epoch(datetime.fromisoformat(r['ended_at']),cache)
                        except (ValueError,KeyError):continue
                        if ss!='unique' or es!='unique' or not lo<=start<hi:continue
                        sn,en=norm_name(r.get('start_station_name')),norm_name(r.get('end_station_name'))
                        if sn not in mapping or en not in mapping:continue
                        counters['named_app32_endpoints']+=1
                        if not r.get('start_station_id') or not r.get('end_station_id'):continue
                        a,_=endpoint_match(sn,r.get('start_lat'),r.get('start_lng'),start,mapping)
                        b,_=endpoint_match(en,r.get('end_lat'),r.get('end_lng'),end,mapping)
                        if not a or not b or not lo<=end<hi:continue
                        counters['mapped_app32_trips']+=1;pair=(a,b);scope=split_at(start,scopes) or 'purge'
                        duration=end-start;eligible_duration=60<=duration<=21600
                        same_split_end=scope!='purge' and split_at(end,scopes)==scope
                        observable_outcome=observable(start,observed[a]) and observable(end,observed[b])
                        counters['both_endpoints_outcome_observable']+=int(observable_outcome)
                        istrain=train['lo']<=start<train['hi'] and train['lo']<=end<train['hi'] and eligible_duration
                        if istrain:counters['eligible_training_rides']+=1;training_od.setdefault(pair,[]).append(duration)
                        supported=int(supports.get(pair,{}).get('training_trips',0))>=20
                        groups=['all_mapped',scope]
                        for group in groups:
                            f=fallback.setdefault(group,dict(mapped_requests=0,geometric_fallback_requests=0,eligible_duration_requests=0,eligible_duration_fallback_requests=0))
                            f['mapped_requests']+=1;f['geometric_fallback_requests']+=int(not supported)
                            f['eligible_duration_requests']+=int(eligible_duration);f['eligible_duration_fallback_requests']+=int(eligible_duration and not supported)
                        ages=[];open_flags=[]
                        for sid in (a,b):
                            ix=bisect.bisect_right(observed[sid],start)-1
                            ages.append(start-observed[sid][ix] if ix>=0 else None)
                            open_flags.append(bool(flags[sid][ix]) if ix>=0 else False)
                        for threshold in [600,900,1200]:
                            retained=all(age is not None and age<=threshold for age in ages)
                            for group in groups:
                                f=fresh.setdefault((group,threshold),dict(requests=0,both_endpoint_context_fresh=0,both_fresh_and_open=0,context_and_outcomes_retained=0,retained_request_for_replay_protocol=0))
                                f['requests']+=1;f['both_endpoint_context_fresh']+=int(retained)
                                f['both_fresh_and_open']+=int(retained and all(open_flags));f['context_and_outcomes_retained']+=int(retained and observable_outcome)
                                f['retained_request_for_replay_protocol']+=int(retained and all(open_flags) and observable_outcome and eligible_duration and same_split_end)
                        normalized.append(dict(start_station_id=a,end_station_id=b,request_time=start,return_time=end,duration_seconds=duration,split=scope,
                            train_OD_eligible=istrain,pair_supported_by_final_training_table=supported,pickup_return_observable=observable_outcome,
                            base_start_age_seconds=ages[0],base_end_age_seconds=ages[1],both_contexts_open=all(open_flags),return_stays_in_request_split=same_split_end,
                            replay_15min_request_retained=all(age is not None and age<=900 for age in ages) and all(open_flags) and observable_outcome and eligible_duration and same_split_end))
        print('Audited app32 trips',src['month'],flush=True)
    for pair,values in training_od.items():
        row=supports[pair]
        if len(values)!=int(row['training_trips']) or float(np.median(values))!=float(row['median_seconds']):raise ValueError('Training OD replay differs from preserved audit')
    if len(training_od)!=len(supports):raise ValueError('Training OD pair set differs')
    request_source=sha(data_root/'download_manifest.json')
    for ordinal,row in enumerate(normalized):
        row['request_id']=hashlib.sha256(f"{request_source}|{protocol['cohort_sha256']}|{ordinal}".encode()).hexdigest()
    pq.write_table(pa.Table.from_pylist(normalized),target/'mapped_app32_requests.parquet',compression='zstd')
    out=reports/'trip_od';out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'planner_od.csv',planner)
    weekly_od=write_weekly_od(normalized,planner,train,target,out)
    fallrows=[dict(split=k,**v,fallback_proportion=v['geometric_fallback_requests']/v['mapped_requests'],
        valid_duration_fallback_proportion=v['eligible_duration_fallback_requests']/v['eligible_duration_requests'] if v['eligible_duration_requests'] else None,
        interpretation='Support from final training-only OD table; train percentages are descriptive coverage, not causal within-training replay') for k,v in fallback.items()]
    write_csv(out/'fallback_by_request_split.csv',fallrows)
    freshrows=[dict(request_set='mapped_app32_completed_rides',split=group,max_age_minutes=threshold//60,**v,
        retained_rate=v['both_endpoint_context_fresh']/v['requests'],excluded=v['requests']-v['both_endpoint_context_fresh']) for (group,threshold),v in fresh.items()]
    # Complement trip-time sampling with a fixed station-time grid denominator.
    for threshold in [600,900,1200]:
        for scope in scopes:
            requests=np.arange(((scope['lo']-360+599)//600)*600+360,scope['hi'],600,dtype=np.int64)
            kept=sum(int((asof_indices(observed[sid],requests,threshold)>=0).sum()) for sid in sorted(selected));count=len(requests)*len(selected)
            freshrows.append(dict(request_set='fixed_10min_station_grid',split=scope['name'],max_age_minutes=threshold//60,requests=count,both_endpoint_context_fresh=kept,
                both_fresh_and_open=None,context_and_outcomes_retained=None,retained_rate=kept/count,excluded=count-kept))
    write_csv(reports/'freshness/freshness_comparison.csv',freshrows)
    supported=sum(r['meets_20_trip_rule'] for r in planner);observed_pairs=len(training_od)
    summary=dict(**counters,station_count=32,mapping_rate=counters['mapped_app32_trips']/counters['named_app32_endpoints'],
        mapping_denominator='Trips naming both historical app32 endpoints with departure in declared window; not full-network trips',
        observed_training_OD_pairs=observed_pairs,OD_pairs_20plus=supported,all_ordered_app32_pairs=len(planner),
        fallback_pair_proportion_all=(len(planner)-supported)/len(planner),fallback_pair_proportion_observed=(observed_pairs-supported)/observed_pairs,
        request_fallback=fallrows,fit_cutoff_utc=iso(train['hi']),training_min_trip_time_utc=iso(min(r['request_time'] for r in normalized if r['train_OD_eligible'])),
        training_max_trip_end_utc=iso(max(r['return_time'] for r in normalized if r['train_OD_eligible'])),
        policy='Both trip times in train, duration 60s..6h; >=20 training rides -> median; otherwise 1.3 * haversine /4 m/s',
        source_manifest_sha256=sha(data_root/'download_manifest.json'),preserved_OD_sha256=sha(project/'reports/chicago_historical_audit/app32/od_ride_times.csv'),
        script_sha256=sha(Path(__file__)),normalized_request_table_sha256=sha(target/'mapped_app32_requests.parquet'),
        training_replay_weekly_OD=weekly_od,weekly_fit_violation_count=sum(epoch(r['source_max_trip_end_utc'])>=epoch(r['fit_cutoff_utc']) for r in weekly_od if r['training_rides']),
        normalization='All point-level mapped requests remain external; no raw trip rows in project',test_did_not_fit_OD=True)
    write_json(out/'audit_summary.json',summary)
    write_json(reports/'freshness/audit_summary.json',dict(replay_max_age_seconds=900,live_max_age_seconds=300,
        choice='Keep pre-existing 15-minute replay bound; do not select a new threshold using held-out outcomes',
        timestamp_policy='Latest valid recorded observation <= decision time; publication latency unmeasured',comparisons=freshrows,
        source_request_table_sha256=summary['normalized_request_table_sha256']))
    print(json.dumps({k:summary[k] for k in ['named_app32_endpoints','mapped_app32_trips','eligible_training_rides','observed_training_OD_pairs','OD_pairs_20plus','fallback_pair_proportion_all']},indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd());p.add_argument('--data-root',type=Path,required=True);p.add_argument('--reports',type=Path,default=Path('reports/final_pipeline_audit'))
    args=p.parse_args()
    if args.data_root.resolve().is_relative_to(args.project_root.resolve()):p.error('Data root must be external')
    audit(args.project_root,args.data_root,args.reports)


if __name__=='__main__':main()
