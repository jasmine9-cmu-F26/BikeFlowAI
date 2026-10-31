"""Stream four matching official trip ZIPs for the bounded Chicago cohort.

No full trip CSV is unpacked. Only aggregate mapping/support and training-only
OD summaries are stored in the project; raw ZIPs remain outside Git.
"""
from __future__ import annotations
import argparse
import bisect
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile
import duckdb
import numpy as np

from audit_divvy_data import norm_name
from audit_divvy_trips import classify_local


def write_csv(path,rows,fields=None):
    rows=list(rows);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)


def utc_epoch(local,cache):
    if local.tzinfo is not None:return 'unique',int(local.timestamp())
    key=(local.year,local.month,local.day,local.hour)
    if key not in cache:
        middle=local.replace(minute=30,second=0,microsecond=0)
        state,utc=classify_local(middle)
        offset=(middle.replace(tzinfo=timezone.utc)-utc).total_seconds() if utc is not None else None
        cache[key]=(state,offset)
    state,offset=cache[key]
    return (state,None) if state!='unique' else ('unique',int(local.replace(tzinfo=timezone.utc).timestamp()-offset))


def endpoint_match(name,lat,lon,ts,mapping):
    candidates={}
    try:lat=float(lat);lon=float(lon)
    except (ValueError,TypeError):return None,None
    if not math.isfinite(lat) or not math.isfinite(lon):return None,None
    for r in mapping.get(norm_name(name),[]):
        if not r['lo']<=ts<r['hi']:continue
        distance=math.hypot((lat-r['lat'])*111320,(lon-r['lon'])*111320*math.cos(math.radians(lat)))
        if distance<=50:candidates[r['station_id']]=min(distance,candidates.get(r['station_id'],float('inf')))
    if len(candidates)!=1:return None,None
    sid=next(iter(candidates));return sid,candidates[sid]


def observable(ts,times,tolerance=300):
    if not times:return False
    right=bisect.bisect_left(times,ts);options=[]
    if right<len(times):options.append(times[right])
    if right:options.append(times[right-1])
    return bool(options) and min(abs(t-ts) for t in options)<=tolerance


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--reports',type=Path,default=Path('reports/chicago_historical_audit'))
    p.add_argument('--manifests',type=Path,default=Path('data/manifests/chicago'))
    args=p.parse_args();root=args.data_root.resolve();out=args.reports;maps=args.manifests
    manifest=json.loads((root/'download_manifest.json').read_text());audit=json.loads((out/'audit_summary.json').read_text())
    with (maps/'selected_stations.csv').open(encoding='utf-8',newline='') as f:selected={r['station_id'] for r in csv.DictReader(f)}
    mapping={}
    with (maps/'station_id_map.csv').open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            r.update(lo=int(datetime.fromisoformat(r['first_observed_utc'].replace('Z','+00:00')).timestamp()),
                     hi=int(datetime.fromisoformat(r['interval_end_utc_exclusive'].replace('Z','+00:00')).timestamp()),lat=float(r['lat']),lon=float(r['lon']))
            mapping.setdefault(r['name_norm'],[]).append(r)
    con=duckdb.connect()
    table=con.sql('SELECT station_id,timestamp FROM read_parquet(?) WHERE num_bikes_available>=0 AND num_docks_available>=0 AND is_in_service IS NOT NULL ORDER BY station_id,timestamp',params=[str(root/'processed/snapshots.parquet')]).to_arrow_table()
    observed={}
    for r in table.to_pylist():observed.setdefault(r['station_id'],[]).append(r['timestamp'])
    con.close()
    lo=int(datetime.fromisoformat(audit['sample_start_utc'].replace('Z','+00:00')).timestamp());hi=int(datetime.fromisoformat(audit['sample_end_utc_exclusive'].replace('Z','+00:00')).timestamp())
    train=audit['splits'][0];train_lo=int(datetime.fromisoformat(train['start_utc'].replace('Z','+00:00')).timestamp());train_hi=int(datetime.fromisoformat(train['end_utc_exclusive'].replace('Z','+00:00')).timestamp())
    totals={k:0 for k in ['raw_rows','invalid_timestamp_rows','DST_excluded_rows','starts_in_sample_window','both_names_in_cohort_and_window',
        'both_endpoints_mapped_in_sample','both_selected_endpoints','both_selected_endpoints_observable','eligible_training_OD_rides']}
    monthly=[];od={};evidence={};cache={}
    for src in manifest['files']:
        if src['kind']!='trips':continue
        stats={k:0 for k in totals};month=src['month']
        with zipfile.ZipFile(root/src['path']) as archive:
            members=[x for x in archive.namelist() if x.endswith('.csv') and not x.startswith('__MACOSX/')]
            for member in members:
                with archive.open(member) as binary:
                    rows=csv.DictReader(io.TextIOWrapper(binary,encoding='utf-8-sig'))
                    for r in rows:
                        stats['raw_rows']+=1
                        try:start=datetime.fromisoformat(r['started_at']);end=datetime.fromisoformat(r['ended_at'])
                        except (ValueError,KeyError):stats['invalid_timestamp_rows']+=1;continue
                        ss,start=utc_epoch(start,cache);es,end=utc_epoch(end,cache)
                        if ss!='unique' or es!='unique':stats['DST_excluded_rows']+=1;continue
                        if not lo<=start<hi:continue
                        stats['starts_in_sample_window']+=1
                        sn,en=norm_name(r.get('start_station_name')),norm_name(r.get('end_station_name'))
                        if sn not in mapping or en not in mapping:continue
                        stats['both_names_in_cohort_and_window']+=1
                        if not r.get('start_station_id') or not r.get('end_station_id'):continue
                        a,ad=endpoint_match(sn,r.get('start_lat'),r.get('start_lng'),start,mapping)
                        b,bd=endpoint_match(en,r.get('end_lat'),r.get('end_lng'),end,mapping)
                        if not a or not b or not lo<=end<hi:continue
                        stats['both_endpoints_mapped_in_sample']+=1
                        for side,tripid,sid,ts,dist in [('start',r['start_station_id'],a,start,ad),('end',r['end_station_id'],b,end,bd)]:
                            key=(month,tripid,sid)
                            e=evidence.setdefault(key,dict(endpoint_count=0,min_epoch=ts,max_epoch=ts,max_distance_m=0))
                            e['endpoint_count']+=1;e['min_epoch']=min(e['min_epoch'],ts);e['max_epoch']=max(e['max_epoch'],ts);e['max_distance_m']=max(e['max_distance_m'],dist)
                        if a not in selected or b not in selected:continue
                        stats['both_selected_endpoints']+=1
                        if observable(start,observed[a]) and observable(end,observed[b]):stats['both_selected_endpoints_observable']+=1
                        duration=end-start
                        if train_lo<=start<train_hi and train_lo<=end<train_hi and 60<=duration<=21600:
                            stats['eligible_training_OD_rides']+=1;od.setdefault((a,b),[]).append(duration)
        for k,v in stats.items():totals[k]+=v
        monthly.append(dict(month=month,**stats,source_zip_sha256=src['sha256']))
        print(f"Official trips {month}: {stats['raw_rows']:,} raw, {stats['both_endpoints_mapped_in_sample']:,} cohort-mapped",flush=True)
    write_csv(out/'trip_overlap_by_month.csv',monthly)
    write_csv(maps/'trip_station_id_map.csv',[dict(month=k[0],trip_station_id=k[1],historical_station_id=k[2],**v,
        method='unique exact historical name + <=50m + observed metadata interval',status='provisional_sample_evidence') for k,v in sorted(evidence.items())],
        ['month','trip_station_id','historical_station_id','endpoint_count','min_epoch','max_epoch','max_distance_m','method','status'])
    od_rows=[dict(start_station_id=a,end_station_id=b,training_trips=len(values),median_seconds=float(np.median(values)),
        p90_seconds=float(np.quantile(values,.9)),meets_20_trip_rule=len(values)>=20) for (a,b),values in sorted(od.items())]
    write_csv(out/'od_ride_times.csv',od_rows,['start_station_id','end_station_id','training_trips','median_seconds','p90_seconds','meets_20_trip_rule'])
    result=dict(**totals,mapping_success_among_named_cohort=totals['both_endpoints_mapped_in_sample']/totals['both_names_in_cohort_and_window'] if totals['both_names_in_cohort_and_window'] else 0,
        selected_trip_observation_support=totals['both_selected_endpoints_observable']/totals['both_selected_endpoints'] if totals['both_selected_endpoints'] else 0,
        selected_station_count=len(selected),observed_OD_pairs=len(od_rows),OD_pairs_20plus=sum(r['meets_20_trip_rule'] for r in od_rows),
        raw_storage='Original four ZIPs only; full CSV files were streamed, not unpacked',
        timezone_policy='Naive trip timestamps interpreted as America/Chicago using explicit IANA fold/gap policy; not independently annotated in CSV',
        mapping_scope='Bounded 50-station sample: trips outside the cohort are out of scope, not mapping failures',
        replay_scope='Nearest valid snapshot within +/-5min is quantized observation support, not exact continuous-time or causal pre-checkout state',
        ride_time_policy='Mapped training-selected endpoints; both trip times in training; 60s..6h duration; no test/tune/calibration ride-time estimation',
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'trip_overlap.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'trip_overlap.md').write_text(f'''# Matching-period official Divvy trips and OD audit

Streamed **{totals['raw_rows']:,}** actual rows from four official ZIPs; no full CSV was unpacked. **{totals['starts_in_sample_window']:,}** trip starts are inside the declared sample period.
The audit covers 50 historical candidate stations, not the entire network. Trips whose endpoints are outside that cohort are out of scope, not failed mappings.

- Trips with both endpoint names in the audited cohort and start inside the window: **{totals['both_names_in_cohort_and_window']:,}**.
- Both endpoints mapped by exact historical name, unique identity, <=50m geometry, and observed metadata interval: **{totals['both_endpoints_mapped_in_sample']:,}** ({100*result['mapping_success_among_named_cohort']:.2f}% of the named-cohort denominator).
- Trips with both endpoints among the training-selected {len(selected)} stations: **{totals['both_selected_endpoints']:,}**.
- Those selected-cohort trips with pickup and return valid snapshots within ±5 min: **{totals['both_selected_endpoints_observable']:,}** ({100*result['selected_trip_observation_support']:.2f}%).
- Eligible training-only rides for OD estimates: **{totals['eligible_training_OD_rides']:,}**.
- Observed OD pairs: **{len(od_rows):,}**; pairs with >=20 training trips: **{result['OD_pairs_20plus']:,}**. Use the proposal's geometric fallback for unsupported pairs.

Source IDs, trip codes, and 2026 GBFS IDs remain separate string namespaces. Mapping does not copy current metadata into the past. Naive trip times follow the explicit America/Chicago policy; ambiguous/nonexistent local times are excluded ({totals['DST_excluded_rows']:,} rows here).

The observation-support number reflects approximate 10-minute ground truth, not exact arrival stock before a real checkout/return. Trip events themselves change inventory, and completed rides omit unmet demand. Final replay timing, interpolation exclusions, and causal feature rules must be approved before reporting model/policy performance.

`trip_station_id_map.csv` records aggregate correspondence evidence. `od_ride_times.csv` uses only training rides (both endpoints in training, duration 60 seconds to 6 hours). No tuning/calibration/test trips estimate OD medians.
''',encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
