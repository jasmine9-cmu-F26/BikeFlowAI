"""Audit CityBikes Divvy change events without inventing polling heartbeats.

Observed event counts and nearest-event label retention are conditional on
inventory changes. Silence is never filled as known unchanged/empty inventory.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa

HORIZONS=[7,14,15,21,28,30,35,42,45,49,56,60]
TOLERANCES=[210,300,450]
GRIDS=[(420,210),(900,300),(900,450)]


def iso(t):
    return datetime.fromtimestamp(int(t),timezone.utc).isoformat().replace('+00:00','Z')


def write_csv(path,rows,fields=None):
    rows=list(rows); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0])); w.writeheader(); w.writerows(rows)


def nearest_valid_matches(times,valid,targets,lo,hi,after_times=None):
    """Filter validity BEFORE nearest search; ties choose earlier; no split leak."""
    candidates=np.flatnonzero(valid & (times>=lo) & (times<hi))
    if not len(candidates):
        return np.full(len(targets),-1,dtype=np.int64),np.full(len(targets),np.inf)
    t=times[candidates]
    minimum=np.searchsorted(t,after_times,side='right') if after_times is not None else np.zeros(len(targets),dtype=np.int64)
    has_candidate=minimum<len(t)
    right=np.maximum(np.searchsorted(t,targets),minimum)
    left=np.maximum(right-1,minimum)
    right=right.clip(0,len(t)-1);left=left.clip(0,len(t)-1)
    index=np.where(abs(t[left]-targets)<=abs(t[right]-targets),left,right)
    result=candidates[index]
    errors=abs(times[result]-targets).astype(float)
    result=np.where(has_candidate,result,-1);errors=np.where(has_candidate,errors,np.inf)
    return result,errors


def observed_grid_coverage(t,lo,hi,step,tolerance):
    t=t[(t>=lo)&(t<hi)]
    slots=(t+step//2)//step
    good=(abs(slots*step-t)<=tolerance)&(slots*step>=lo)&(slots*step<hi)
    n=len(np.unique(slots[good])); den=max(0,math.ceil(hi/step)-math.ceil(lo/step))
    return n,den,n/den if den else 0


def chronological_splits(first,last):
    week=604800; monday=345600
    lo=monday+math.ceil((first-monday)/week)*week
    hi=monday+math.floor((last-monday)/week)*week
    n=(hi-lo)//week
    if n<14: raise ValueError('Insufficient complete calendar weeks for 8+ weeks train and 2+ test under four-way split')
    bounds=[0,int(n*.6),int(n*.75),int(n*.85),n]
    return [dict(split=name,start=lo+bounds[i]*week+(3600 if i else 0),end=lo+bounds[i+1]*week)
            for i,name in enumerate(['train','tune','calibration','test'])]


def station_tables(con,pattern):
    relation=con.sql('SELECT * FROM read_parquet(?) ORDER BY station_id,timestamp,source_month,citybikes_id',params=[pattern])
    reader=relation.to_arrow_reader(100000)
    current=None; chunks=[]
    for batch in reader:
        ids=batch.column('station_id').to_numpy(zero_copy_only=False)
        cuts=np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1,len(ids)]
        for lo,hi in zip(cuts[:-1],cuts[1:]):
            if current is not None and ids[lo]!=current:
                yield current,pa.Table.from_batches(chunks).combine_chunks()
                chunks=[]
            current=ids[lo]; chunks.append(batch.slice(int(lo),int(hi-lo)))
    if chunks: yield current,pa.Table.from_batches(chunks).combine_chunks()


def norm_name(value):
    return ' '.join(str(value or '').casefold().split())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--reports',type=Path,default=Path('reports/divvy_data_audit'))
    p.add_argument('--manifests',type=Path,default=Path('data/manifests/divvy'))
    args=p.parse_args(); root=args.data_root.resolve(); out=args.reports; manifests=args.manifests
    out.mkdir(parents=True,exist_ok=True); manifests.mkdir(parents=True,exist_ok=True)
    extraction=json.loads((root/'processed/extraction_manifest.json').read_text())
    downloads=json.loads((root/'download_manifest.json').read_text())
    pattern=str(root/'processed/events/*.parquet').replace('\\','/')
    con=duckdb.connect(); con.execute("SET memory_limit='2GB'");con.execute('SET threads=4')
    scratch=root/'processed/audit_tmp';scratch.mkdir(exist_ok=True)
    con.execute('SET temp_directory=?',[str(scratch)])
    rows,first,last=con.execute('SELECT count(*),min(timestamp),max(timestamp) FROM read_parquet(?)',[pattern]).fetchall()[0]
    splits=chronological_splits(first,last)
    scopes=[dict(split='archive',start=first,end=last+1),*splits]
    train=splits[0]
    write_csv(manifests/'split_manifest.csv',[dict(split=s['split'],start_utc=iso(s['start']),
        end_utc_exclusive=iso(s['end']),duration_weeks=(s['end']-s['start'])/604800,
        purge_before_minutes=0 if i==0 else 60,status='provisional_not_training_ready') for i,s in enumerate(splits)])
    coverage=[];gaps=[];changes=[];epochs=[];quality={};balance={};all_labels={};by_station_labels={}
    event_times=[];dedup_rows=0;duplicate_rows=0;conflict_rows=0
    live_info=json.loads((root/'raw/live/station_information.json').read_text())
    live_status=json.loads((root/'raw/live/station_status.json').read_text())
    live_by_id={str(s['station_id']):s for s in live_info['data']['stations']}
    live_status_by_id={str(s['station_id']):s for s in live_status['data']['stations']}
    metadata_fields=['name','lat','lon','capacity']
    identity_fields=['name','lat','lon']
    live_matches=0
    for number,(sid,table) in enumerate(station_tables(con,pattern),1):
        a={c:table[c].to_numpy(zero_copy_only=False) for c in table.column_names}
        original_t=a['timestamp'].astype(np.int64)
        keep=np.r_[True,original_t[1:]!=original_t[:-1]]
        duplicates=int((~keep).sum());duplicate_rows+=duplicates
        conflicted_t=set()
        for ix in np.flatnonzero(~keep):
            if any(a[k][ix]!=a[k][ix-1] for k in ['num_bikes_available','num_docks_available','is_renting','is_returning']):
                conflicted_t.add(int(original_t[ix]))
        a={k:v[keep] for k,v in a.items()}; t=a['timestamp'].astype(np.int64);n=len(t);dedup_rows+=n
        event_times.append(t)
        conflicts=np.isin(t,list(conflicted_t));conflict_rows+=int(conflicts.sum())
        bikes=a['num_bikes_available'];docks=a['num_docks_available'];cap=a['capacity']
        counts=np.isfinite(bikes)&np.isfinite(docks)&(bikes>=0)&(docks>=0)
        flags=np.array([x is not None for x in a['is_renting']])&np.array([x is not None for x in a['is_returning']])
        physical=np.isfinite(cap)&(cap>0)&(a['is_virtual']!=True)
        valid=counts&flags&physical&~conflicts
        age=t-a['last_reported']
        fresh=valid&np.isfinite(age)&(a['last_reported']>0)&(age>=0)&(age<=300)
        bad_bike=(bikes<1)|(a['is_renting']!=True)
        bad_dock=(docks<1)|(a['is_returning']!=True)
        masks={'missing_or_negative_counts':~counts,'unknown_operating_flags':~flags,
            'capacity_zero_or_missing':~(np.isfinite(cap)&(cap>0)),
            'explicit_virtual':a['is_virtual']==True,'virtual_flag_missing':np.array([x is None for x in a['is_virtual']]),
            'last_reported_zero_or_missing':~np.isfinite(age)|(a['last_reported']<=0),
            'report_age_gt300s':np.isfinite(age)&(a['last_reported']>0)&(age>300),
            'future_report_time':age<0,'not_renting':a['is_renting']!=True,
            'not_returning':a['is_returning']!=True,
            'is_installed_unavailable':np.array([x is None for x in a['is_installed']]),
            'disabled_counts_unavailable':~np.isfinite(a['num_bikes_disabled'])|~np.isfinite(a['num_docks_disabled']),
            'usable_inventory_sum_ne_capacity':counts&np.isfinite(cap)&((bikes+docks)!=cap)}
        for key,mask in masks.items():quality[key]=quality.get(key,0)+int(mask.sum())
        train_idx=np.flatnonzero((t>=train['start'])&(t<train['end']))
        tr0=int(train_idx[0]) if len(train_idx) else 0
        trlat=float(np.nanmedian(a['lat'][train_idx])) if len(train_idx) else float('nan')
        trlon=float(np.nanmedian(a['lon'][train_idx])) if len(train_idx) else float('nan')
        movement=np.hypot((a['lat']-trlat)*111320,(a['lon']-trlon)*111320*np.cos(np.deg2rad(trlat)))
        row=dict(station_id=sid,name=a['name'][tr0],first_utc=iso(t[0]),last_utc=iso(t[-1]),
                 event_rows=n,fresh_event_rows=int(fresh.sum()),duplicates_removed=duplicates,
                 train_lat=trlat,train_lon=trlon,
                 train_max_displacement_m=float(np.nanmax(movement[train_idx])) if len(train_idx) else '',
                 live_uid_match=sid in live_by_id)
        live_matches+=int(sid in live_by_id)
        for scope in scopes:
            for step,tol in GRIDS:
                observed,expected,ratio=observed_grid_coverage(t[fresh],scope['start'],scope['end'],step,tol)
                prefix=f"{scope['split']}_grid{step//60}_tol{tol}"
                row[prefix+'_observed_slots']=observed;row[prefix+'_expected_slots']=expected;row[prefix+'_coverage']=ratio
        coverage.append(row)
        dt=np.diff(t)/60
        gaps.append(dict(station_id=sid,change_intervals=len(dt),median_minutes=float(np.median(dt)) if len(dt) else '',
            p90_minutes=float(np.quantile(dt,.9)) if len(dt) else '',max_minutes=float(dt.max()) if len(dt) else '',
            intervals_gt14=int((dt>14).sum()),intervals_gt30=int((dt>30).sum()),intervals_gt60=int((dt>60).sum()),
            interpretation='change silence; unchanged inventory and collection outage cannot be separated'))
        # An inventory epoch avoids pairing a base with a different capacity/location.
        signature=[(str(a['name'][j]),round(float(a['lat'][j]),6),round(float(a['lon'][j]),6),
                    int(cap[j]) if np.isfinite(cap[j]) else None) for j in range(n)]
        changed=np.r_[True,np.fromiter((signature[j]!=signature[j-1] for j in range(1,n)),bool,count=max(0,n-1))]
        epoch=changed.cumsum()
        for j in np.flatnonzero(changed)[1:]:
            for key in metadata_fields:
                if a[key][j]!=a[key][j-1]:
                    changes.append(dict(station_id=sid,timestamp_utc=iso(t[j]),field=key,
                        old_value=a[key][j-1],new_value=a[key][j],source_month=a['source_month'][j]))
        # Identity intervals ignore capacity-only changes; capacity is not inferred from live data.
        identity=[s[:3] for s in signature]
        identity_changed=np.r_[True,np.fromiter((identity[j]!=identity[j-1] for j in range(1,n)),bool,count=max(0,n-1))]
        cuts=np.r_[np.flatnonzero(identity_changed),n]
        for lo,hi in zip(cuts[:-1],cuts[1:]):
            lm=live_by_id.get(sid,{})
            epochs.append(dict(station_id=sid,citybikes_id=a['citybikes_id'][lo],
                gbfs_station_id=a['gbfs_station_id'][lo],name=a['name'][lo],name_norm=norm_name(a['name'][lo]),
                lat=a['lat'][lo],lon=a['lon'][lo],first_observed_utc=iso(t[lo]),
                interval_end_utc_exclusive=iso(t[hi]) if hi<n else iso(t[-1]+1),
                last_observed_utc=iso(t[hi-1]),current_gbfs_uid_match=sid in live_by_id,
                current_trip_short_name=lm.get('short_name',''),
                mapping_status='historical_uid_and_observed_metadata_interval_not_polling_coverage'))
        local_labels={}
        for scope in scopes:
            label=scope['split']; inside=(t>=scope['start'])&(t<scope['end'])
            for policy,mask in [('structural_observed',valid),('fresh_observed',fresh)]:
                m=mask&inside;key=(label,policy)
                values=dict(rows=int(m.sum()),bike_unavailable=int((m&bad_bike).sum()),dock_unavailable=int((m&bad_dock).sum()))
                dest=balance.setdefault(key,dict(rows=0,bike_unavailable=0,dock_unavailable=0))
                for k,v in values.items():dest[k]+=v
            for horizon in HORIZONS:
                base=np.flatnonzero(fresh&inside&(t+horizon*60<scope['end']))
                targets=t[base]+horizon*60
                ix,error=nearest_valid_matches(t,fresh,targets,scope['start'],scope['end'],after_times=t[base])
                present=ix>=0;safe_ix=ix.clip(0,n-1)
                same_epoch=present&(epoch[safe_ix]==epoch[base])
                for tolerance in TOLERANCES:
                    hit=same_epoch&(error<=tolerance)
                    values=dict(base_rows=len(base),retained_labels=int(hit.sum()),
                        bike_unavailable=int((hit&bad_bike[safe_ix]).sum()),
                        dock_unavailable=int((hit&bad_dock[safe_ix]).sum()),
                        abs_error_sum_seconds=float(error[hit].sum()))
                    key=(label,horizon,tolerance);local_labels[key]=values
                    dest=all_labels.setdefault(key,{k:0 for k in values})
                    for k,v in values.items():dest[k]+=v
        by_station_labels[sid]=local_labels
        if number%100==0:print(f'Audited {number} Divvy identities',flush=True)
    # Predeclared central-Chicago area and training-only ranking; no test outcomes used.
    candidates=[r for r in coverage if np.isfinite(r['train_lat']) and 41.85<=r['train_lat']<=41.92
                and -87.68<=r['train_lon']<=-87.60 and r['train_max_displacement_m']!=''
                and r['train_max_displacement_m']<=50]
    candidates.sort(key=lambda r:(-r['train_grid7_tol210_coverage'],r['station_id']))
    candidate_ids={r['station_id'] for r in candidates[:20]}
    for r in coverage:r['training_top20_candidate']=r['station_id'] in candidate_ids
    labels=[]
    candidate_stats={}
    for sid in candidate_ids:
        for key,values in by_station_labels[sid].items():
            dest=candidate_stats.setdefault(key,{k:0 for k in values})
            for k,v in values.items():dest[k]+=v
    for group,items in [('all_stations',all_labels),('training_top20_candidates',candidate_stats)]:
        for (scope,horizon,tolerance),s in sorted(items.items()):
            n=s['base_rows'];k=s['retained_labels']
            labels.append(dict(group=group,split=scope,horizon_minutes=horizon,tolerance_seconds=tolerance,**s,
                retention=k/n if n else '',mean_abs_error_seconds=s['abs_error_sum_seconds']/k if k else '',
                bike_unavailable_rate=s['bike_unavailable']/k if k else '',
                dock_unavailable_rate=s['dock_unavailable']/k if k else ''))
    write_csv(out/'coverage_by_station.csv',coverage)
    write_csv(out/'gap_summary.csv',gaps)
    write_csv(out/'label_retention.csv',labels)
    write_csv(out/'class_balance.csv',[dict(split=k[0],policy=k[1],**v,
        bike_unavailable_rate=v['bike_unavailable']/v['rows'] if v['rows'] else '',
        dock_unavailable_rate=v['dock_unavailable']/v['rows'] if v['rows'] else '') for k,v in balance.items()])
    write_csv(out/'station_changes.csv',changes,['station_id','timestamp_utc','field','old_value','new_value','source_month'])
    write_csv(manifests/'station_id_map.csv',epochs)
    write_csv(manifests/'candidate_stations.csv',[dict(station_id=r['station_id'],name=r['name'],
        train_lat=r['train_lat'],train_lon=r['train_lon'],train_grid7_tol210_coverage=r['train_grid7_tol210_coverage'],
        train_max_displacement_m=r['train_max_displacement_m'],status='provisional_training_only_candidate') for r in candidates[:20]],
        ['station_id','name','train_lat','train_lon','train_grid7_tol210_coverage','train_max_displacement_m','status'])
    write_csv(manifests/'selected_stations.csv',[],['station_id','selection_status','approved_rule_version'])
    network=np.unique(np.concatenate(event_times));nd=np.diff(network)/60
    network_gaps=[dict(start_utc=iso(a),end_utc=iso(b),minutes=(b-a)/60,
                      interpretation='network-wide absence of change records; outage not proven')
                  for a,b in zip(network[:-1],network[1:]) if b-a>900]
    write_csv(out/'network_silences.csv',network_gaps,['start_utc','end_utc','minutes','interpretation'])
    weeks=[];s=splits[0]['start']
    while s+604800<=splits[-1]['end']:
        e=s+604800;hits,den,ratio=observed_grid_coverage(network,s,e,420,210)
        weeks.append(dict(start_utc=iso(s),end_utc_exclusive=iso(e),
            network_change_slots=hits,expected_slots=den,network_change_slot_ratio=ratio,
            interpretation='network activity only; not proof each station was polled'))
        s=e
    write_csv(out/'weekly_coverage.csv',weeks)
    status_values=list(live_status_by_id.values())
    live_check=dict(captured_at_utc=next(x['captured_at_utc'] for x in downloads['live'] if x['name']=='station_status'),
        discovery_url='https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json',
        status_version=live_status.get('version'),information_stations=len(live_by_id),status_stations=len(live_status_by_id),
        station_information_only=len(set(live_by_id)-set(live_status_by_id)),
        status_only=len(set(live_status_by_id)-set(live_by_id)),
        historical_identities_with_exact_current_gbfs_uid=live_matches,
        missing_installed=sum('is_installed' not in s for s in status_values),
        missing_renting=sum('is_renting' not in s for s in status_values),
        missing_returning=sum('is_returning' not in s for s in status_values),
        timezone=json.loads((root/'raw/live/system_information.json').read_text())['data']['timezone'],
        publisher_license_url=json.loads((root/'raw/live/system_information.json').read_text())['data'].get('license_url'),
        license_evidence='MobilityDatabase catalog reports CC-BY-4.0; captured publisher system_information has no license_url',
        observation_scope='single captured live sample, not a historical uptime audit')
    (out/'live_gbfs_check.json').write_text(json.dumps(live_check,indent=2)+'\n')
    evidence={k:v for k,v in downloads.items() if k not in ('files',)}
    evidence['files']=downloads['files']
    (out/'download_manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')
    summary=dict(decision='NEED_TO_RESTRICT',training_ready=False,
        reason='Change-only archive has no complete heartbeat; station selection/rule approval and some GBFS feature semantics remain unresolved',
        historical_role='observed change-event features and nearest-observed valid labels, conditional on revised sampling design',
        first_observation_utc=iso(first),last_observation_utc=iso(last),
        calendar_days=(last-first)/86400,monthly_parts=len(extraction['parts']),raw_event_rows=rows,
        deduplicated_event_rows=dedup_rows,duplicates_removed=duplicate_rows,conflicting_timestamps=conflict_rows,
        station_identities=len(coverage),network_change_timestamps=len(network),
        network_change_interval_median_minutes=float(np.median(nd)),network_change_interval_p90_minutes=float(np.quantile(nd,.9)),
        longest_network_silence_minutes=float(nd.max()),network_silences_gt15=len(network_gaps),
        quality=quality,training_top20_candidates=len(candidate_ids),approved_selected_stations=0,
        historical_metadata_change_events=len(changes),historical_identity_intervals=len(epochs),
        splits=[dict(split=s['split'],start_utc=iso(s['start']),end_utc_exclusive=iso(s['end']),weeks=(s['end']-s['start'])/604800) for s in splits],
        label_policy='fresh base and strictly future target, report age 0..300s, nonnegative counts, known renting/returning, positive capacity, not explicitly virtual, same metadata epoch, nearest valid within tolerance, no split crossing',
        bias='event-conditional retention and class balance; not uniform-time occupancy estimates',
        reconstruction='no unlimited carry-forward; silence not treated as unchanged/empty',
        experiment_horizons_minutes=HORIZONS,experiment_tolerances_seconds=TOLERANCES,
        weather='optional_not_required_for_Divvy_MVP',
        raw_download_bytes=downloads['total_raw_download_bytes'],
        audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        normalization_manifest_sha256=hashlib.sha256((root/'processed/extraction_manifest.json').read_bytes()).hexdigest(),
        runtime=dict(duckdb=duckdb.__version__,numpy=np.__version__,pyarrow=pa.__version__),
        license_status='CityBikes ODbL-1.0 compilation + separate operator terms; Divvy trips restricted dataset license; live CC-BY-4.0 is catalog evidence, publisher confirmation pending')
    (out/'audit_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    report=build_report(summary,labels,coverage,live_check)
    (out/'data_audit.md').write_text(report,encoding='utf-8')
    con.close()
    print(json.dumps({k:summary[k] for k in ['decision','raw_event_rows','station_identities','training_top20_candidates','first_observation_utc','last_observation_utc']},indent=2),flush=True)


def build_report(s,labels,coverage,live):
    pct=lambda x:f'{100*x:.2f}%'
    lines=[]
    for r in labels:
        if r['group']=='training_top20_candidates' and r['split']=='archive' and r['tolerance_seconds']==210 and r['horizon_minutes']%7==0:
            lines.append(f"| {r['horizon_minutes']//7} | {r['horizon_minutes']} | {r['base_rows']:,} | {pct(r['retention']) if r['retention']!='' else 'N/A'} |")
    splitlines=[f"| {r['split']} | {r['start_utc']} | {r['end_utc_exclusive']} | {r['weeks']:.3f} |" for r in s['splits']]
    changes='\n'.join(f"- {k}: {v:,} ({pct(v/s['deduplicated_event_rows'])})." for k,v in s['quality'].items())
    best=max((r['train_grid7_tol210_coverage'] for r in coverage),default=0)
    return f'''# Divvy data audit

Audit date: 2026-10-30 (America/Los_Angeles). **Decision: NEED TO RESTRICT; not training-ready yet.**

## Sources and local storage

- CityBikes historical Divvy change records: model feature/label source under an explicitly revised observation policy.
- Official Divvy monthly trips: OD requests and training-only ride-time estimates.
- Official Divvy GBFS: live inference source; discovered from its official auto-discovery document.
- Downloaded **{s['monthly_parts']} CityBikes months and matching trip months**, {s['raw_download_bytes']:,} bytes. Raw and processed files are outside the Git project, under the user-selected data root. Only code, manifests, source checks, and aggregate reports belong in BikeFlowAI.
- Full provenance: `download_manifest.json`; licenses and attribution: `licensing_and_overlap.md`.

## Actual historical data

- Date range: **{s['first_observation_utc']} → {s['last_observation_utc']}** ({s['calendar_days']:.2f} calendar days).
- Raw records: **{s['raw_event_rows']:,}**; deduplicated events: **{s['deduplicated_event_rows']:,}**; station identities: **{s['station_identities']:,}**.
- Duplicate rows removed: {s['duplicates_removed']:,}; conflicting station timestamps: {s['conflicting_timestamps']:,}, excluded from valid labels.
- Source `nuid` is retained as the publisher GBFS station ID; CityBikes' own hash ID is preserved separately.

**These are inventory-change events, not complete regular snapshots.** The upstream collector drops observations when bike/dock counts do not change. A quiet station may have constant inventory or may be unobserved. Status-flag-only changes can also be suppressed. We do not use unbounded forward-fill or interpret silence as empty/unchanged.
The collector timestamp is treated as UTC and the provider `extra.last_updated` is retained separately. Provider report age is checked; zero/missing dates are not fresh.

## Coverage and gaps

`coverage_by_station.csv` measures the fraction of fixed grid centers with a directly observed fresh event within tolerance. This is an observed-event coverage measure, **not an estimate of polling success**. It can penalize a perfectly functioning station whose inventory stayed constant.
The best station's training seven-minute / ±3.5-minute observed-event coverage is {pct(best)}. The old Bay Wheels 90% criterion cannot simply be carried over to this different record type.
`gap_summary.csv` reports station change intervals; `network_silences.csv` reports intervals with no network change records for >15 min. These are outage candidates, not confirmed collection outages.
Network change timestamp interval median / p90: {s['network_change_interval_median_minutes']:.3f} / {s['network_change_interval_p90_minutes']:.3f} min; longest network silence: {s['longest_network_silence_minutes']:.2f} min.

## Chronological train / tune / calibrate / test

Complete UTC calendar weeks, cumulative 60/15/10/15 split, with 60-minute separation before later splits. No label search crosses a split. The purge must be reviewed if the final horizon/tolerance policy changes.

| Split | Start UTC | End UTC (exclusive) | Weeks |
|---|---|---|---:|
{chr(10).join(splitlines)}

These periods have enough calendar duration for 8 weeks training and 2 later weeks testing; observation support and rare events must still be checked per station/horizon. Splits are **provisional**, not certified training tables.

## Label retention and sampling comparison

Fresh base and target events require nonnegative bike/dock counts, known renting/returning flags, positive capacity, no explicit virtual-station flag, and provider report age 0–300 seconds. `is_installed` and disabled counts are not supplied by this historical schema and remain missing; they are not invented from today's GBFS.
Targets use **nearest valid events**, filtering validity before search, with deterministic earlier ties. Matched label observations must be strictly later than their request/base time, even when tolerance is wider than a short horizon. Base/target metadata epochs must match. Missing targets are dropped.

Training-only exploratory selection ranks a predeclared central-Chicago area by training observed-event coverage and excludes >50m training relocation. **{s['training_top20_candidates']} candidates**, zero approved selections. Test outcomes do not choose stations.

For the exploratory candidates, original k=1…8 and ±3.5 min (whole archive diagnostics):

| k | Horizon (min) | Eligible fresh bases | Retained labels |
|---:|---:|---:|---:|
{chr(10).join(lines)}

`label_retention.csv` also compares 15/30/45/60-minute horizons, 210/300/450-second tolerances, all stations versus training candidates, and every split. Wider tolerances improve retention at the cost of time precision; no setting is approved automatically.
Rates are **conditional on observing a change**, and are not evidence of uniform-time replay coverage or final lag-feature completeness. `class_balance.csv` is likewise event-weighted, not time-weighted occupancy.

## Field quality and station changes

Counts below overlap; denominator {s['deduplicated_event_rows']:,} deduplicated events:

{changes}

`station_changes.csv` contains {s['historical_metadata_change_events']:,} observed metadata changes. The Divvy `station_id_map.csv` contains {s['historical_identity_intervals']:,} observed identity intervals. These intervals describe metadata provenance, not uninterrupted status reporting. Capacity-minus-bikes must not replace measured dock counts; disabled inventory is unavailable.

## Trips, timezones, and live inference

The official GBFS reports **{live['timezone']}**, not Pacific time. Historical collector epochs are UTC. Naive trip timestamps require America/Chicago localization with explicit ambiguous/nonexistent DST handling. Trip-date coverage, mapped endpoints, OD support, and training-only ride-time estimates are reported separately in `trip_overlap.json` / `trip_overlap.md` when the trip audit is complete.
The captured official GBFS has {live['information_stations']} information stations and {live['status_stations']} status stations. Historical identities with exact current publisher UID matches: {live['historical_identities_with_exact_current_gbfs_uid']}. A current UID match does not establish continuous historic station availability. See `live_gbfs_check.json`.
Live inference has a richer schema than the historical change archive; model features must use the historical/live intersection or explicitly handle missing fields. The current one-time live capture is not a feed-uptime audit.

## Decision and remaining acceptance

**NEED TO RESTRICT**: there is substantially more calendar history available, but event-only semantics, absent heartbeat/status-only changes, unapproved sampling thresholds, and missing historical GBFS fields prevent an unconditional PASS for the original complete-snapshot/replay architecture.
Use only directly observed, freshness-checked labels for an explicitly event-conditioned experiment, or obtain a historical polling/heartbeat source before claiming uniform-time replay. A new GBFS collector can extend history but cannot retroactively certify past silence.
Complete trip mapping/DST and frozen sampling rules before training. Preserve explicit exclusions, retain the held-out test, and do not call the provisional candidate list a final 20-station selection.
'''


if __name__=='__main__':main()
