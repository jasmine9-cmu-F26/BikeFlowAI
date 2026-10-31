"""Audit a bounded official Chicago snapshot sample, retaining unchanged polls.

Station eligibility is determined from the training split only. Calendar gaps
remain gaps; no filling or zero-inventory imputation is performed.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime,timedelta,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
import duckdb
import numpy as np

from audit_divvy_data import nearest_valid_matches,norm_name
from audit_divvy_trips import dst_intervals

ZONE=ZoneInfo('America/Chicago')
HORIZONS=[10,20,30,40,50,60]


def iso(value):return datetime.fromtimestamp(int(value),timezone.utc).isoformat().replace('+00:00','Z')


def epoch_local(value):return int(datetime.fromisoformat(value).replace(tzinfo=ZONE).timestamp())


def write_csv(path,rows,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True);rows=list(rows)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)


def grid_coverage(t,lo,hi,phase=300):
    t=t[(t>=lo)&(t<hi)];slots=(t-phase+300)//600;centers=slots*600+phase
    good=(centers>=lo)&(centers<hi)&(abs(centers-t)<=300)
    observed=len(np.unique(slots[good]));expected=max(0,math.ceil((hi-phase)/600)-math.ceil((lo-phase)/600))
    return observed,expected,observed/expected if expected else 0


def current_match(name,lat,lon,stations):
    candidates=[]
    for s in stations:
        distance=math.hypot((float(s['lat'])-lat)*111320,(float(s['lon'])-lon)*111320*math.cos(math.radians(lat)))
        if distance<=50:candidates.append((s,distance,norm_name(name)==norm_name(s['name'])))
    exact=[x for x in candidates if x[2]]
    if len(exact)==1:return 'exact_name_geo_unique',exact[0][0],exact[0][1]
    if len(exact)>1:return 'ambiguous',None,None
    if len(candidates)==1:return 'spatial_candidate_name_changed_needs_review',candidates[0][0],candidates[0][1]
    return ('no_match' if not candidates else 'ambiguous'),None,None


def normalize(con,root,manifest):
    paths=[str(root/f['path']) for f in manifest['files'] if f['kind']=='snapshots']
    for f in manifest['files']:
        if f['kind']=='snapshots' and hashlib.sha256((root/f['path']).read_bytes()).hexdigest()!=f['saved_sha256']:
            raise ValueError('Snapshot chunk hash mismatch')
    con.execute("""CREATE TEMP TABLE source AS SELECT *,try_cast(timestamp AS TIMESTAMP) AS local_ts
        FROM read_json(?,format='array',columns={id:'VARCHAR',timestamp:'VARCHAR',station_name:'VARCHAR',
            total_docks:'VARCHAR',docks_in_service:'VARCHAR',available_docks:'VARCHAR',available_bikes:'VARCHAR',
            status:'VARCHAR',latitude:'VARCHAR',longitude:'VARCHAR',record:'VARCHAR'},filename=true)""",[paths])
    con.execute('CREATE TEMP TABLE bad_local(start_local TIMESTAMP,end_local TIMESTAMP,kind VARCHAR)')
    year=datetime.fromisoformat(manifest['settings']['start_local']).year
    endyear=datetime.fromisoformat(manifest['settings']['end_local_exclusive']).year
    bad=dst_intervals(datetime(year,1,1),datetime(endyear+1,1,1))
    if bad:con.executemany('INSERT INTO bad_local VALUES (?,?,?)',bad)
    con.execute("""CREATE TEMP TABLE prepared AS SELECT 'chicago:'||s.id AS station_id,s.id AS historical_station_id,
        s.station_name AS name,s.timestamp AS source_local_timestamp,
        cast(epoch(timezone('America/Chicago',s.local_ts)) AS BIGINT) AS timestamp,
        try_cast(s.total_docks AS BIGINT) AS capacity,try_cast(s.docks_in_service AS BIGINT) AS docks_in_service,
        try_cast(s.available_bikes AS BIGINT) AS num_bikes_available,try_cast(s.available_docks AS BIGINT) AS num_docks_available,
        s.status,CASE WHEN s.status='In Service' THEN true WHEN s.status='Not In Service' THEN false ELSE NULL END AS is_in_service,
        try_cast(s.latitude AS DOUBLE) AS lat,try_cast(s.longitude AS DOUBLE) AS lon,s.record AS source_record,
        split_part(replace(s.filename,'\\','/'),'/',-1) AS source_file,'official_poll_snapshot' AS record_type,
        s.local_ts IS NULL OR EXISTS(SELECT 1 FROM bad_local b WHERE s.local_ts>=b.start_local AND s.local_ts<b.end_local) AS invalid_time
        FROM source s""")
    bad_times=con.execute('SELECT count(*) FROM prepared WHERE invalid_time').fetchall()[0][0]
    con.execute("""CREATE TEMP TABLE conflicts AS SELECT station_id,timestamp FROM prepared WHERE NOT invalid_time
        GROUP BY station_id,timestamp HAVING count(DISTINCT concat_ws('|',num_bikes_available,num_docks_available,status,capacity))>1""")
    conflicts=con.execute('SELECT count(*) FROM conflicts').fetchall()[0][0]
    con.execute("""CREATE TEMP TABLE snapshots AS SELECT * EXCLUDE(rn,invalid_time) FROM (
        SELECT p.*,row_number() OVER (PARTITION BY p.station_id,p.timestamp ORDER BY p.source_record) AS rn
        FROM prepared p LEFT JOIN conflicts c ON p.station_id=c.station_id AND p.timestamp=c.timestamp
        WHERE NOT p.invalid_time AND c.station_id IS NULL) WHERE rn=1""")
    output=root/'processed/snapshots.parquet';output.parent.mkdir(parents=True,exist_ok=True)
    con.execute('COPY (SELECT * FROM snapshots ORDER BY station_id,timestamp) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(output)])
    n=con.execute('SELECT count(*) FROM snapshots').fetchall()[0][0]
    return n,bad_times,conflicts,output


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--reports',type=Path,default=Path('reports/chicago_historical_audit'))
    p.add_argument('--manifests',type=Path,default=Path('data/manifests/chicago'))
    args=p.parse_args();root=args.data_root.resolve();out=args.reports;maps=args.manifests
    out.mkdir(parents=True,exist_ok=True);maps.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((root/'download_manifest.json').read_text())
    if not manifest.get('completed_at_utc'):p.error('Bounded download is incomplete')
    con=duckdb.connect();con.execute("SET TimeZone='UTC'");con.execute('SET threads=4')
    n,bad_times,conflicts,parquet=normalize(con,root,manifest)
    start_local=datetime.fromisoformat(manifest['settings']['start_local']);end_local=datetime.fromisoformat(manifest['settings']['end_local_exclusive'])
    lo,hi=epoch_local(start_local.isoformat()),epoch_local(end_local.isoformat())
    weeks=(end_local-start_local).days//7
    bounds=[0,int(weeks*.6),int(weeks*.75),int(weeks*.85),weeks]
    splits=[dict(split=name,start=epoch_local((start_local+timedelta(weeks=bounds[i])).isoformat())+(3600 if i else 0),
        end=epoch_local((start_local+timedelta(weeks=bounds[i+1])).isoformat())) for i,name in enumerate(['train','tune','calibration','test'])]
    scopes=[dict(split='sample',start=lo,end=hi),*splits];train=splits[0]
    # Derive phase from training observations only, with one-minute rounding to
    # absorb seconds of source scheduler jitter. No test timestamps choose it.
    train_t=con.execute('SELECT DISTINCT timestamp FROM snapshots WHERE timestamp>=? AND timestamp<?',[train['start'],train['end']]).fetchall()
    if not train_t:raise ValueError('No training snapshots')
    phases=[int((t[0]%600+30)//60)*60%600 for t in train_t]
    phase=max(set(phases),key=lambda x:(phases.count(x),-x))
    current_root=root.parent/'current_validation';current_state=json.loads((current_root/'state.json').read_text())
    current_info=json.loads(gzip.decompress((current_root/'metadata'/(current_state['metadata_content_sha256']+'.json.gz')).read_bytes()))['data']['stations']
    coverage=[];gaps=[];labels_by_station={};balances_by_station={};metadata=[];changes=[];live=[];quality={};all_t=[]
    unchanged=0;interval_count=0
    ids=[r[0] for r in con.execute('SELECT DISTINCT station_id FROM snapshots ORDER BY station_id').fetchall()]
    for sid in ids:
        table=con.sql('SELECT * FROM snapshots WHERE station_id=? ORDER BY timestamp',params=[sid]).to_arrow_table()
        a={k:table[k].to_numpy(zero_copy_only=False) for k in table.column_names};t=a['timestamp'].astype(np.int64);all_t.append(t)
        counts=np.isfinite(a['num_bikes_available'])&np.isfinite(a['num_docks_available'])&(a['num_bikes_available']>=0)&(a['num_docks_available']>=0)
        status_known=np.array([x is not None for x in a['is_in_service']]);in_service=a['is_in_service']==True
        valid=counts&status_known&np.isfinite(a['lat'])&np.isfinite(a['lon'])
        bad_bike=(a['num_bikes_available']==0)|~in_service;bad_dock=(a['num_docks_available']==0)|~in_service
        tr=(t>=train['start'])&(t<train['end']);trix=np.flatnonzero(tr);first=int(trix[0]) if len(trix) else 0
        lat=float(np.median(a['lat'][tr])) if len(trix) else float(a['lat'][0]);lon=float(np.median(a['lon'][tr])) if len(trix) else float(a['lon'][0])
        movement=np.hypot((a['lat']-lat)*111320,(a['lon']-lon)*111320*np.cos(np.deg2rad(lat)))
        row=dict(station_id=sid,historical_station_id=str(a['historical_station_id'][0]),name=a['name'][first],sample_rows=len(t),
            first_utc=iso(t[0]),last_utc=iso(t[-1]),train_lat=lat,train_lon=lon,
            train_max_displacement_m=float(movement[tr].max()) if len(trix) else None,
            train_name_versions=len(set(a['name'][tr])),train_capacity_versions=len(set(a['capacity'][tr])),
            train_in_service_fraction=float(in_service[tr].mean()) if len(trix) else 0)
        for scope in scopes:
            key=scope['split'];_obs,den,pres=grid_coverage(t,scope['start'],scope['end'],phase)
            good,_den,cov=grid_coverage(t[valid],scope['start'],scope['end'],phase)
            row.update({key+'_expected_slots':den,key+'_observed_slots':_obs,key+'_coverage':pres,key+'_valid_coverage':cov})
        coverage.append(row)
        dt=np.diff(t)/60;unchanged+=int(((np.diff(a['num_bikes_available'])==0)&(np.diff(a['num_docks_available'])==0)).sum());interval_count+=len(dt)
        gaps.append(dict(station_id=sid,median_minutes=float(np.median(dt)),p90_minutes=float(np.quantile(dt,.9)),
            longest_gap_minutes=float(dt.max()),gaps_gt15=int((dt>15).sum()),gaps_gt30=int((dt>30).sum()),gaps_gt60=int((dt>60).sum())))
        for key,mask in {'bad_counts':~counts,'unknown_status':~status_known,'closed_status':~in_service,
            'docks_service_sum_mismatch':a['docks_in_service']!=(a['num_bikes_available']+a['num_docks_available']),
            'in_service_docks_gt_capacity':a['docks_in_service']>a['capacity']}.items():quality[key]=quality.get(key,0)+int(mask.sum())
        cuts=[0]
        for j in range(1,len(t)):
            different=any(a[k][j]!=a[k][j-1] for k in ['name','lat','lon','capacity'])
            if different:
                for k in ['name','lat','lon','capacity']:
                    if a[k][j]!=a[k][j-1]:changes.append(dict(station_id=sid,timestamp_utc=iso(t[j]),field=k,old_value=a[k][j-1],new_value=a[k][j]))
            if different or t[j]-t[j-1]>1800:cuts.append(j)
        cuts.append(len(t))
        kind,current,distance=current_match(row['name'],lat,lon,current_info)
        live.append(dict(station_id=sid,historical_station_id=row['historical_station_id'],historical_name=row['name'],
            historical_lat=lat,historical_lon=lon,match_status=kind,current_station_id=str(current['station_id']) if current else '',
            current_name=current['name'] if current else '',current_short_name=current.get('short_name','') if current else '',distance_m=distance))
        for first,end in zip(cuts[:-1],cuts[1:]):
            metadata.append(dict(station_id=sid,historical_station_id=row['historical_station_id'],name=a['name'][first],name_norm=norm_name(a['name'][first]),
                lat=a['lat'][first],lon=a['lon'][first],first_observed_utc=iso(t[first]),
                interval_end_utc_exclusive=iso(min(t[end-1]+600,t[end] if end<len(t) else hi)),last_observed_utc=iso(t[end-1]),
                current_station_id=str(current['station_id']) if current and kind=='exact_name_geo_unique' else '',
                current_trip_short_name=current.get('short_name','') if current and kind=='exact_name_geo_unique' else '',
                mapping_status='provisional_observed_snapshot_metadata_interval_split_at_gt30min_gaps'))
        local=[];local_balance=[]
        for scope in scopes:
            inside=(t>=scope['start'])&(t<scope['end']);known=inside&valid
            local_balance.append(dict(split=scope['split'],valid_rows=int(known.sum()),bike_unavailable=int((known&bad_bike).sum()),dock_unavailable=int((known&bad_dock).sum()),
                empty_count=int((known&(a['num_bikes_available']==0)).sum()),full_count=int((known&(a['num_docks_available']==0)).sum()),closed_status=int((known&~in_service).sum())))
            for h in HORIZONS:
                base=np.flatnonzero(inside&valid&in_service&(t+h*60<scope['end']))
                target=t[base]+h*60
                ix,error=nearest_valid_matches(t,valid,target,scope['start'],scope['end'],after_times=t[base])
                safe=ix.clip(0,len(t)-1)
                distance=np.hypot((a['lat'][safe]-a['lat'][base])*111320,(a['lon'][safe]-a['lon'][base])*111320*np.cos(np.deg2rad(a['lat'][base])))
                hit=(ix>=0)&(error<=300)&(distance<=50)
                local.append(dict(split=scope['split'],horizon_minutes=h,tolerance_seconds=300,base_rows=len(base),retained_labels=int(hit.sum()),
                    bike_unavailable=int((hit&bad_bike[safe]).sum()),dock_unavailable=int((hit&bad_dock[safe]).sum()),matching_error_sum_seconds=float(error[hit].sum())))
        labels_by_station[sid]=local;balances_by_station[sid]=local_balance
    selected=[r for r in coverage if r['train_valid_coverage']>=.9 and r['train_max_displacement_m'] is not None and r['train_max_displacement_m']<=50
              and r['train_name_versions']==1 and r['train_capacity_versions']==1 and r['train_in_service_fraction']>=.8]
    selected.sort(key=lambda r:(-r['train_valid_coverage'],r['station_id']));selected=selected[:50];chosen={r['station_id'] for r in selected}
    for row in coverage:row['training_selected']=row['station_id'] in chosen
    for row in live:row['training_selected']=row['station_id'] in chosen
    labels=[];balances=[]
    for group,cohort in [('all_sample_stations',set(ids)),('training_selected',chosen)]:
        for scope in scopes:
            rows=[x for sid in cohort for x in balances_by_station[sid] if x['split']==scope['split']]
            values={key:sum(r[key] for r in rows) for key in ['valid_rows','bike_unavailable','dock_unavailable','empty_count','full_count','closed_status']}
            den=values['valid_rows'];balances.append(dict(group=group,split=scope['split'],**values,
                bike_unavailable_rate=values['bike_unavailable']/den if den else '',dock_unavailable_rate=values['dock_unavailable']/den if den else ''))
            for h in HORIZONS:
                rows=[x for sid in cohort for x in labels_by_station[sid] if x['split']==scope['split'] and x['horizon_minutes']==h]
                values={k:sum(r[k] for r in rows) for k in ['base_rows','retained_labels','bike_unavailable','dock_unavailable','matching_error_sum_seconds']}
                den=values['base_rows'];kept=values['retained_labels']
                labels.append(dict(group=group,split=scope['split'],horizon_minutes=h,tolerance_seconds=300,**values,
                    retention=kept/den if den else '',mean_matching_error_seconds=values['matching_error_sum_seconds']/kept if kept else ''))
    write_csv(out/'coverage_by_station.csv',coverage);write_csv(out/'gap_summary.csv',gaps);write_csv(out/'label_retention.csv',labels)
    write_csv(out/'class_balance.csv',balances);write_csv(out/'station_changes.csv',changes,['station_id','timestamp_utc','field','old_value','new_value'])
    write_csv(out/'live_station_overlap.csv',live)
    write_csv(maps/'station_id_map.csv',metadata)
    selected_fields=['station_id','historical_station_id','name','train_lat','train_lon','train_valid_coverage','train_in_service_fraction','training_selected']
    write_csv(maps/'selected_stations.csv',[{k:r[k] for k in selected_fields} for r in selected],selected_fields)
    write_csv(maps/'candidate_stations.csv',[{k:r[k] for k in selected_fields} for r in coverage],selected_fields)
    write_csv(maps/'split_manifest.csv',[dict(split=s['split'],start_utc=iso(s['start']),end_utc_exclusive=iso(s['end']),
        weeks=(s['end']-s['start'])/604800,purge_before_minutes=0 if i==0 else 60,status='provisional_sample_design_not_model_ready') for i,s in enumerate(splits)])
    times=np.unique(np.concatenate(all_t));diff=np.diff(times)/60
    longgaps=[dict(start_utc=iso(a),end_utc=iso(b),gap_minutes=(b-a)/60) for a,b in zip(times[:-1],times[1:]) if b-a>1800]
    write_csv(out/'network_gaps.csv',longgaps,['start_utc','end_utc','gap_minutes'])
    min_cov=min((r[s['split']+'_valid_coverage'] for r in selected for s in splits),default=0)
    min_ret=min((r['retention'] for r in labels if r['group']=='training_selected' and r['split']!='sample' and r['retention']!=''),default=0)
    passed=len(chosen)>=20 and min_cov>=.9 and min_ret>=.9
    summary=dict(decision='PASS_BOUNDED_SNAPSHOT_FEASIBILITY' if passed else 'NEED_TO_RESTRICT_PERIOD_OR_COHORT',training_ready=False,
        decision_scope='Only the declared period and bounded training-selected cohort; not the entire Chicago dataset or a trained/live model',
        dataset_id=DATASET if 'DATASET' in globals() else 'eq45-8inv',
        source_name='City of Chicago Divvy Bicycle Stations - Historical',
        requested_start_local=manifest['settings']['start_local'],requested_end_local_exclusive=manifest['settings']['end_local_exclusive'],
        sample_start_utc=iso(lo),sample_end_utc_exclusive=iso(hi),first_observation_utc=iso(times[0]),last_observation_utc=iso(times[-1]),
        raw_rows=manifest['snapshot_rows'],normalized_rows=n,invalid_or_DST_excluded_rows=bad_times,conflicting_station_timestamps=conflicts,
        stations_audited=len(ids),stations_selected_from_training=len(chosen),
        interval_median_minutes=float(np.median(diff)),interval_p90_minutes=float(np.quantile(diff,.9)),longest_network_gap_minutes=float(diff.max()),
        unchanged_inventory_transition_fraction=unchanged/interval_count if interval_count else 0,
        expected_grid_minutes=10,grid_phase_seconds_learned_from_training=phase,
        minimum_selected_station_valid_coverage_across_splits=min_cov,minimum_selected_label_retention_across_splits_horizons=min_ret,
        current_2026_exact_name_geo_matches=sum(r['match_status']=='exact_name_geo_unique' and r['training_selected'] for r in live),
        current_2026_mapping_capture_utc=current_state.get('last_success_utc'),
        splits=[dict(split=s['split'],start_utc=iso(s['start']),end_utc_exclusive=iso(s['end']),weeks=(s['end']-s['start'])/604800) for s in splits],
        quality=quality,documented_dataset_time_period=manifest['dataset_metadata']['time_period'],
        license=manifest['dataset_metadata']['license'],license_id=manifest['dataset_metadata']['licenseId'],
        timezone_policy=manifest['timezone_policy'],
        semantics='Full recorded snapshots; unchanged inventories retained; source broad In Service status is not separate GBFS renting/returning/installed flags',
        download_manifest_sha256=hashlib.sha256((root/'download_manifest.json').read_bytes()).hexdigest(),
        audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        raw_compressed_snapshot_bytes=manifest['compressed_snapshot_bytes'],trip_zip_bytes=manifest['trip_zip_bytes'])
    (out/'audit_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'download_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'data_audit.md').write_text(report(summary,coverage,labels,balances),encoding='utf-8')
    con.close();print(json.dumps(summary,indent=2),flush=True)


def report(s,coverage,labels,balances):
    pct=lambda x:f'{100*x:.2f}%'
    splitrows=[f"| {x['split']} | {x['start_utc']} | {x['end_utc_exclusive']} | {x['weeks']:.3f} |" for x in s['splits']]
    labelrows=[f"| {x['horizon_minutes']} | {x['base_rows']:,} | {pct(x['retention']) if x['retention']!='' else 'N/A'} |" for x in labels if x['group']=='training_selected' and x['split']=='sample']
    b=next(x for x in balances if x['group']=='training_selected' and x['split']=='sample')
    return f'''# Official Chicago Divvy snapshot feasibility audit

Audit date: 2026-10-30. **{s['decision']}**. This is a bounded source/cohort feasibility result, not certification of a complete model or arbitrary exact-time truth.

## Sample and provenance

- Source: [Chicago official dataset eq45-8inv](https://data.cityofchicago.org/d/eq45-8inv), classified historical-only; [Data.gov description](https://catalog.data.gov/dataset/divvy-bicycle-stations-historical).
- Declared local window: **{s['requested_start_local']} → {s['requested_end_local_exclusive']}**. The source's floating times are explicitly interpreted as America/Chicago; raw wall times are retained. The API schema itself provides no timezone offset.
- **{s['raw_rows']:,}** downloaded rows, **{s['normalized_rows']:,}** normalized rows, **{s['stations_audited']}** sampled stations. The full ~242-million-row dataset was not exported or independently recounted.
- Initial candidates came only from a predeclared central-Chicago training anchor, sorted by exact station ID. Final eligibility uses training coverage, service fraction, capacity/name stability, and <=50m training movement; test outcomes do not select stations.
- Raw compressed snapshot bytes: {s['raw_compressed_snapshot_bytes']:,}; matching-month official trip ZIP bytes: {s['trip_zip_bytes']:,}. Raw/processed files stay outside Git. `download_manifest.json` records query URLs, bounds, hashes and source metadata.
- Source station IDs and current GBFS IDs remain strings; no floating-point conversion of long identifiers.

## Cadence, coverage, missingness

- Unique cohort poll interval median / p90: **{s['interval_median_minutes']:.3f} / {s['interval_p90_minutes']:.3f} min**.
- Longest gap in the sampled network timestamps: **{s['longest_network_gap_minutes']:.2f} min**; see `network_gaps.csv` and per-station `gap_summary.csv`.
- Grid: 10 minutes, phase {s['grid_phase_seconds_learned_from_training']} seconds (learned from training only), ±5 min observation tolerance. Denominators use the entire declared split, not each station's lifetime. Presence and valid-state coverage are separate.
- Selected from training: **{s['stations_selected_from_training']}** stations. Lowest selected valid coverage across all four splits: **{pct(s['minimum_selected_station_valid_coverage_across_splits'])}**.
- Unchanged consecutive inventory fraction: **{pct(s['unchanged_inventory_transition_fraction'])}**. These repeated full observations are retained, unlike change-event-only archives.
- Source metadata documents: `{s['documented_dataset_time_period']}`. Additional gaps found by a sample must be reported rather than hidden by compressing calendar time.

## Chronological splits

The requested window is divided into whole local calendar weeks using cumulative 60/15/10/15 boundaries, with 60-minute separation before later splits. Source/feature timestamps are UTC after documented localization; targets and matched observations cannot cross splits.

| Split | Start UTC | End UTC (exclusive) | Weeks |
|---|---|---|---:|
{chr(10).join(splitrows)}

## Availability labels

For each open, valid base snapshot, the target is t+h. Search valid snapshots first, choose the nearest strictly future observation within ±5 min, break ties earlier, and reject >50m base/target relocation. No filling across missing intervals is performed.
Bike availability requires source `In Service` and available_bikes>0; dock availability requires `In Service` and available_docks>0. Known closed status is a negative availability outcome. Missing counts/status are exclusions, never empty labels.
The old archive does not expose separate current GBFS installed/renting/returning or disabled-bike flags. The broad status-based historical label and historical/live feature intersection need explicit model-design review.

| Horizon (min) | Eligible bases | Sample label retention |
|---:|---:|---:|
{chr(10).join(labelrows)}

Lowest selected retention over each split/horizon: **{pct(s['minimum_selected_label_retention_across_splits_horizons'])}**. `label_retention.csv` and `class_balance.csv` include all sampled versus training-selected cohorts. Selected sample bike/dock unavailable fractions: **{pct(b['bike_unavailable_rate']) if b['bike_unavailable_rate']!='' else 'N/A'} / {pct(b['dock_unavailable_rate']) if b['dock_unavailable_rate']!='' else 'N/A'}**.
Labels have 10-minute resolution with a documented matching error; this is not exact continuous-time ground truth. Full lag-feature completeness and end-to-end replay are not implemented by this feasibility audit.

## Historical trip and 2026 live identity

`station_id_map.csv` versions observed historical names/coordinates/capacities and splits intervals at >30-minute observation gaps. `live_station_overlap.csv` compares current official GBFS by exact normalized name and <=50m coordinates, requiring uniqueness; name-changed spatial candidates remain unconfirmed.
Current exact name+geometry matches among the selected cohort: **{s['current_2026_exact_name_geo_matches']}**. Current UID/short-code evidence is not copied into past features or treated as proof of continuous operation since the sample year.
Same-period official trip mapping, training-only OD medians, and pickup/return observation support are reported separately in `trip_overlap.md` after the trip audit. Historical IDs, trip station codes, and 2026 GBFS station IDs must not be assumed identical.

## License and acceptance

The publisher labels the dataset **{s['license_id']} / {s['license'].get('name','See Terms of Use')}**, not CC0 or the CityBikes ODbL. Follow the City's [Data Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html), including the required application disclaimer and any additional agency terms. Official trips and live GBFS have separate source-specific terms.

Diagnostic feasibility thresholds are >=20 training-stable stations, >=90% valid coverage in every split, and >=90% label retention per horizon/split. A passing small audit establishes only this sampled source/period/cohort. Final station/rule/split approval, feature generation, historical/live semantics, model evaluation, and old-to-2026 domain shift remain separate tasks.
CityBikes recent records remain supplementary feasibility/identity evidence and are not arbitrary-time ground truth. The new full-GBFS collector provides future current-data sanity checks, not retroactive repairs to old gaps.
'''


if __name__=='__main__':main()
