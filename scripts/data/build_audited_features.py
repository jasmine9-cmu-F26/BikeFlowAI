"""Build separate causal-feature/target Parquet parts and audit their lineage.

Requests use the frozen 10-minute grid. Outcome access is isolated to target
generation, never a feature. All generated rows stay outside Git.
"""
import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from bikeflow_data.temporal import nearest_valid_matches
from pipeline_audit_common import *

ZONE=ZoneInfo('America/Chicago')
LAGS=[10,30,60]
MODEL_FEATURES=['station_id','horizon_minutes','num_bikes_available','num_docks_available','capacity','docks_in_service','is_in_service',
    'base_age_seconds','hour','weekday','is_weekend','capacity_inconsistent']+sum(([f'bike_delta_{m}m',f'dock_delta_{m}m',f'lag_{m}m_missing',f'lag_{m}m_age_seconds',f'lag_{m}m_in_service'] for m in LAGS),[])


def calendar(times,cache):
    result=[]
    for t in times:
        t=int(t)
        if t not in cache:
            d=datetime.fromtimestamp(t,ZONE);cache[t]=(d.weekday(),d.hour)
        result.append(cache[t])
    return np.array(result,dtype=np.int64)


def fit_b2(sid,t,bikes,docks,service,valid,lo,cutoff,cache):
    ix=np.flatnonzero(valid&(t>=lo)&(t<cutoff))
    if not len(ix):return []
    cal=calendar(t[ix],cache);cell=cal[:,0]*24+cal[:,1]
    goodbike=service[ix]&(bikes[ix]>0);gooddock=service[ix]&(docks[ix]>0)
    result=[]
    for weekday in range(7):
        for hour in range(24):
            local=ix[cell==weekday*24+hour];mask=cell==weekday*24+hour;n=len(local);use=n>=20
            result.append(dict(station_id=sid,weekday=weekday,hour=hour,cell_samples=n,station_samples=len(ix),
                bike_available_rate=float(goodbike[mask].mean()) if use else float(goodbike.mean()),
                dock_available_rate=float(gooddock[mask].mean()) if use else float(gooddock.mean()),
                method='weekday_hour_cell' if use else 'station_overall_fallback',fit_cutoff=cutoff,
                source_min_timestamp=int(t[ix].min()),source_max_timestamp=int(t[ix].max())))
    return result


def build_station_features(sid,a,scope,horizons,cache):
    t=np.asarray(a['timestamp'],dtype=np.int64);bikes=np.asarray(a['num_bikes_available']);docks=np.asarray(a['num_docks_available'])
    service=np.asarray(a['is_in_service'],dtype=bool);lat=np.asarray(a['lat']);lon=np.asarray(a['lon'])
    status_known=np.array([v is not None for v in a['is_in_service']],dtype=bool)
    valid=np.isfinite(bikes)&np.isfinite(docks)&(bikes>=0)&(docks>=0)&np.isfinite(lat)&np.isfinite(lon)&status_known
    usable=np.flatnonzero(valid);vt=t[usable]
    request=np.arange(((scope['lo']-360+599)//600)*600+360,scope['hi'],600,dtype=np.int64)
    base_local=asof_indices(vt,request,900);safe_local=base_local.clip(0,max(0,len(vt)-1))
    if not len(vt):return [],[],dict(expected_grid_requests=len(request),fresh_valid_base=0,open_base=0)
    base=usable[safe_local];fresh=base_local>=0;open_base=fresh&service[base]
    q=request[open_base];base=base[open_base]
    if not len(q):return [],[],dict(expected_grid_requests=len(request),fresh_valid_base=int(fresh.sum()),open_base=0)
    cal=calendar(q,cache)
    features=dict(request_time=q,base_snapshot_time=t[base],metadata_timestamp=t[base],feature_timestamp=t[base],
        num_bikes_available=bikes[base],num_docks_available=docks[base],capacity=np.asarray(a['capacity'])[base],docks_in_service=np.asarray(a['docks_in_service'])[base],
        is_in_service=service[base],base_age_seconds=q-t[base],hour=cal[:,1],weekday=cal[:,0],is_weekend=cal[:,0]>=5,
        capacity_inconsistent=np.asarray(a['docks_in_service'])[base]>np.asarray(a['capacity'])[base])
    for minutes in LAGS:
        ix=asof_indices(vt,q-minutes*60,900);safe=usable[ix.clip(0,len(vt)-1)]
        moved=distance_m(lat[safe],lon[safe],lat[base],lon[base])>50
        missing=(ix<0)|moved
        features[f'lag_{minutes}m_snapshot_time']=pa.array(t[safe],mask=missing)
        features[f'lag_{minutes}m_age_seconds']=np.where(missing,np.nan,q-minutes*60-t[safe]).astype(float)
        features[f'bike_delta_{minutes}m']=np.where(missing,np.nan,bikes[base]-bikes[safe]).astype(float)
        features[f'dock_delta_{minutes}m']=np.where(missing,np.nan,docks[base]-docks[safe]).astype(float)
        features[f'lag_{minutes}m_in_service']=pa.array(service[safe],mask=missing)
        features[f'lag_{minutes}m_missing']=missing
    feature_parts=[];label_parts=[]
    for h in horizons:
        # Targets must remain in this split; only the outcome builder reads them.
        target=q+h*60;eligible=target<scope['hi']
        ix,err=nearest_valid_matches(t,valid,target,scope['lo'],scope['hi'],after_times=q)
        safe=ix.clip(0,len(t)-1)
        hit=eligible&(ix>=0)&(err<=300)&(distance_m(lat[safe],lon[safe],lat[base],lon[base])<=50)
        chosen=np.flatnonzero(hit);rq=q[chosen];tx=safe[chosen]
        if not len(chosen):continue
        identifiers=[f'{sid}|{int(v)}|{h}' for v in rq]
        columns={name:(value.take(pa.array(chosen)) if isinstance(value,pa.Array) else value[chosen]) for name,value in features.items()}
        columns.update(row_id=identifiers,station_id=[sid]*len(chosen),split=[scope['name']]*len(chosen),horizon_minutes=np.full(len(chosen),h,dtype=np.int16))
        feature_parts.append(pa.Table.from_pydict(columns))
        label_parts.append(pa.Table.from_pydict(dict(row_id=identifiers,split=[scope['name']]*len(chosen),station_id=[sid]*len(chosen),request_time=rq,
            horizon_minutes=np.full(len(chosen),h,dtype=np.int16),target_time=target[chosen],target_snapshot_time=t[tx],
            target_offset_seconds=t[tx]-target[chosen],bike_unavailable=((bikes[tx]==0)|~service[tx]).astype(np.int8),
            dock_unavailable=((docks[tx]==0)|~service[tx]).astype(np.int8),target_is_in_service=service[tx],target_num_bikes=bikes[tx],target_num_docks=docks[tx])))
    counts=dict(expected_grid_requests=len(request),fresh_valid_base=int(fresh.sum()),open_base=int(open_base.sum()))
    return feature_parts,label_parts,counts


def audit_tables(root,out,protocol,ODsummary,b2fits):
    con=duckdb.connect();con.execute("SET memory_limit='1GB'");con.execute('SET threads=4')
    scratch=root/'audit_tmp';scratch.mkdir(exist_ok=True);con.execute('SET temp_directory=?',[str(scratch)])
    con.read_parquet(str(root/'features/*.parquet')).create_view('features')
    con.read_parquet(str(root/'labels/*.parquet')).create_view('labels')
    con.execute('CREATE VIEW joined AS SELECT f.*,l.target_time,l.target_snapshot_time,l.target_offset_seconds,l.bike_unavailable,l.dock_unavailable FROM features f JOIN labels l USING(row_id)')
    checks={}
    checks['future_base_snapshot']=con.execute('SELECT count(*) FROM features WHERE base_snapshot_time>request_time').fetchall()[0][0]
    checks['future_metadata']=con.execute('SELECT count(*) FROM features WHERE metadata_timestamp>request_time').fetchall()[0][0]
    checks['future_feature_timestamp']=con.execute('SELECT count(*) FROM features WHERE feature_timestamp>request_time').fetchall()[0][0]
    checks['base_too_old']=con.execute('SELECT count(*) FROM features WHERE request_time-base_snapshot_time>900 OR request_time<base_snapshot_time').fetchall()[0][0]
    for m in LAGS:
        checks[f'future_lag_{m}m']=con.execute(f'SELECT count(*) FROM features WHERE lag_{m}m_snapshot_time>request_time-{m*60}').fetchall()[0][0]
        checks[f'stale_lag_{m}m']=con.execute(f'SELECT count(*) FROM features WHERE request_time-{m*60}-lag_{m}m_snapshot_time>900').fetchall()[0][0]
    checks['target_not_future']=con.execute('SELECT count(*) FROM labels WHERE target_snapshot_time<=request_time').fetchall()[0][0]
    checks['target_outside_tolerance']=con.execute('SELECT count(*) FROM labels WHERE abs(target_offset_seconds)>300').fetchall()[0][0]
    checks['duplicate_feature_row_id']=con.execute('SELECT count(*)-count(DISTINCT row_id) FROM features').fetchall()[0][0]
    checks['feature_label_row_mismatch']=con.execute('SELECT abs((SELECT count(*) FROM features)-(SELECT count(*) FROM labels))+(SELECT count(*) FROM features f ANTI JOIN labels l USING(row_id))').fetchall()[0][0]
    checks['target_crosses_split']=0
    for scope in splits(protocol):
        checks['target_crosses_split']+=con.execute('SELECT count(*) FROM labels WHERE split=? AND (request_time<? OR request_time>=? OR target_snapshot_time<? OR target_snapshot_time>=? OR target_time>=?)',[scope['name'],scope['lo'],scope['hi'],scope['lo'],scope['hi'],scope['hi']]).fetchall()[0][0]
    count=con.execute('SELECT count(*) FROM features').fetchall()[0][0]
    missing=[]
    for name in MODEL_FEATURES:
        typename=dict((r[0],r[1]) for r in con.execute('DESCRIBE features').fetchall())[name]
        expr=f'"{name}" IS NULL'+(f' OR isnan("{name}")' if typename in {'DOUBLE','FLOAT'} else '')
        for scope in ['all','train','tune','calibration','test']:
            where='' if scope=='all' else f"WHERE split='{scope}'"
            total,nulls=con.execute(f'SELECT count(*),count(*) FILTER(WHERE {expr}) FROM features {where}').fetchall()[0]
            missing.append(dict(feature=name,split=scope,total_rows=total,missing_rows=nulls,missing_rate=nulls/total if total else None))
    write_csv(out/'feature_missingness.csv',missing)
    group=con.execute('SELECT split,horizon_minutes,count(*) AS rows,sum(bike_unavailable) AS bike_unavailable,sum(dock_unavailable) AS dock_unavailable,avg(bike_unavailable) AS bike_unavailable_rate,avg(dock_unavailable) AS dock_unavailable_rate FROM joined GROUP BY split,horizon_minutes ORDER BY split,horizon_minutes').fetchall()
    write_csv(out/'rows_and_class_balance.csv',[dict(zip(['split','horizon_minutes','rows','bike_unavailable','dock_unavailable','bike_unavailable_rate','dock_unavailable_rate'],r)) for r in group])
    stations=con.execute('SELECT station_id,split,count(*) FROM features GROUP BY station_id,split ORDER BY station_id,split').fetchall()
    write_csv(out/'station_rows.csv',[dict(station_id=s,split=scope,rows=n) for s,scope,n in stations])
    offsets=con.execute('SELECT split,horizon_minutes,min(target_offset_seconds),quantile_cont(target_offset_seconds,0.5),quantile_cont(abs(target_offset_seconds),0.9),max(abs(target_offset_seconds)) FROM labels GROUP BY split,horizon_minutes ORDER BY split,horizon_minutes').fetchall()
    write_csv(out/'target_offset_distribution.csv',[dict(zip(['split','horizon_minutes','minimum_signed_seconds','median_signed_seconds','p90_absolute_seconds','maximum_absolute_seconds'],r)) for r in offsets])
    completeness=[]
    for scope in ['train','tune','calibration','test']:
        n=con.execute('SELECT count(*) FROM features WHERE split=?',[scope]).fetchall()[0][0]
        for m in LAGS:
            missingn=con.execute(f'SELECT count(*) FROM features WHERE split=? AND lag_{m}m_missing',[scope]).fetchall()[0][0]
            completeness.append(dict(split=scope,lag_minutes=m,rows=n,complete_rows=n-missingn,missing_rows=missingn,completeness=(n-missingn)/n))
    write_csv(out/'lag_completeness.csv',completeness)
    trainend=splits(protocol)[0]['hi'];checks['OD_nontraining_fit']=int(epoch(ODsummary['training_max_trip_end_utc'])>=trainend)
    checks['OD_training_week_fit_after_cutoff']=ODsummary.get('weekly_fit_violation_count',0)
    checks['B2_source_at_or_after_fit_cutoff']=sum(r['source_max_timestamp']>=r['fit_cutoff'] for r in b2fits if r['source_rows'])
    checks['B2_fit_beyond_train']=sum(r['fit_cutoff']>trainend for r in b2fits)
    checks['B2_attached_to_training_features']=int(any(n.lower().startswith('b2') for n in MODEL_FEATURES))
    checks['label_columns_in_model_features']=int(any(n.startswith('target') or n in {'bike_unavailable','dock_unavailable'} for n in MODEL_FEATURES))
    write_json(out/'leakage_checks.json',dict(violation_counts=checks,passed=not any(checks.values()),
        categorical_encoding='Raw station strings only; downstream learned encoders/imputers must fit train only',
        station_selection='Existing train qualification plus fixed external 2026 identity scope; held-out labels do not select stations',
        publication_latency='Historical recorded timestamps stand in for unmeasured actual publication latency'))
    if any(checks.values()):raise ValueError('Feature leakage/invariant audit failed: '+str(checks))
    schema=dict(version=1,row_key='station_id|request_time_utc_epoch|horizon_minutes',model_feature_columns=MODEL_FEATURES,
        lineage_columns=['request_time','base_snapshot_time','metadata_timestamp','feature_timestamp']+[f'lag_{m}m_snapshot_time' for m in LAGS],
        never_model_inputs=['row_id','split','target_time','target_snapshot_time','target_offset_seconds','bike_unavailable','dock_unavailable','target_is_in_service','target_num_bikes','target_num_docks'],
        table_layout='features/*.parquet contains only current/past features plus lineage; labels/*.parquet contains future outcomes separately',
        missing_lags='Keep NaN/null + missing flags for LightGBM cold start, no future fill or train/test imputation',
        dropped_inputs=['weather','disabled counts','separate installed/renting/returning flags','historical provider report age (unavailable)'],
        temporal_model_use='Train for fitting, tune for choices, calibration for final calibration, test only final reporting',
        policy_training='Train pool only; OOF/forward predictions required, not generated/certified by this data audit')
    write_json(out/'feature_schema.json',schema)
    splitcounts={name:con.execute('SELECT count(*) FROM features WHERE split=?',[name]).fetchall()[0][0] for name in ['train','tune','calibration','test']}
    result=dict(status='PASS_FEATURE_TABLE_INVARIANTS_UNDER_RECORDED_TIME_ASSUMPTION',feature_rows=count,label_rows=count,
        split_counts=splitcounts,policy_training_pool_rows=splitcounts['train'],policy_prediction_table_created=False,
        feature_table_ready_for_model_handoff=True,model_or_policy_trained=False,all_leakage_violation_counts=checks,
        full_replay_implemented=False,feature_snapshot_source_sha256=sha(root.parent/'snapshots.parquet'),
        code_sha256=sha(Path(__file__)),historical_protocol_unchanged=True)
    write_json(out/'audit_summary.json',result);con.close();return result


def build(project,data_root,reports):
    protocol=read(project/'data/manifests/chicago/app32/data_protocol.json');scopes=splits(protocol);train=scopes[0]
    cohort=sorted(r['station_id'] for r in csvrows(project/protocol['cohort_manifest']))
    root=data_root/'processed/final_pipeline_v1';(root/'features').mkdir(parents=True,exist_ok=True);(root/'labels').mkdir(exist_ok=True)
    if list((root/'features').glob('*.parquet')):raise ValueError('Feature outputs already exist; use a new version/root rather than silently mixing')
    con=duckdb.connect();cache={};exclusions=[];fullb2=[];fitmanifest=[];weekly=[]
    for sid in cohort:
        table=con.sql('SELECT * FROM read_parquet(?) WHERE station_id=? ORDER BY timestamp',params=[str(data_root/'processed/snapshots.parquet'),sid]).to_arrow_table()
        a={name:table[name].to_numpy(zero_copy_only=False) for name in table.column_names};t=a['timestamp'].astype(np.int64)
        valid=(a['num_bikes_available']>=0)&(a['num_docks_available']>=0)&np.array([v is not None for v in a['is_in_service']])
        for week in range(11):
            cutoff=min(train['hi'],train['lo']+week*7*86400)
            values=fit_b2(sid,t,a['num_bikes_available'],a['num_docks_available'],a['is_in_service'].astype(bool),valid,train['lo'],cutoff,cache)
            m=(t>=train['lo'])&(t<cutoff)&valid
            fitmanifest.append(dict(station_id=sid,version='heldout_final' if week==10 else f'train_week_{week}',fit_cutoff=cutoff,source_rows=int(m.sum()),
                source_min_timestamp=int(t[m].min()) if m.any() else None,source_max_timestamp=int(t[m].max()) if m.any() else None,
                use='tune/calibration/test only' if week==10 else 'Only requests at/after this week cutoff, before next cutoff; first week B1 fallback'))
            for r in values:r['version']='heldout_final' if week==10 else f'train_week_{week}'
            if week==10:fullb2.extend(values)
            else:weekly.extend(values)
        for scope in scopes:
            features,labels,counts=build_station_features(sid,a,scope,protocol['horizons_minutes'],cache)
            filename=sid.replace(':','_')+'_'+scope['name']+'.parquet'
            if features:
                pq.write_table(pa.concat_tables(features),root/'features'/filename,compression='zstd')
                pq.write_table(pa.concat_tables(labels),root/'labels'/filename,compression='zstd')
            exclusions.append(dict(station_id=sid,split=scope['name'],**counts,retained_feature_label_rows=sum(len(p) for p in features)))
        print('Built feature/label parts',sid,flush=True)
    con.close()
    b2=root/'B2';b2.mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(weekly),b2/'training_expanding_week_rates.parquet',compression='zstd')
    pq.write_table(pa.Table.from_pylist(fullb2),b2/'heldout_training_fit_rates.parquet',compression='zstd')
    out=reports/'features';out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'base_and_target_exclusions.csv',exclusions);write_csv(out/'B2_fit_manifest.csv',fitmanifest);write_csv(out/'B2_heldout_rates.csv',fullb2)
    result=audit_tables(root,out,protocol,read(reports/'trip_od/audit_summary.json'),fitmanifest)
    files=[dict(path=p.relative_to(root).as_posix(),sha256=sha(p),bytes=p.stat().st_size,rows=pq.read_metadata(p).num_rows) for p in sorted(root.rglob('*.parquet'))]
    write_json(out/'generated_manifest.json',dict(files=files,feature_schema_sha256=sha(out/'feature_schema.json'),
        contract=final_contract(project),raw_tables_outside_Git=True,table_root='external 2021 sample / processed/final_pipeline_v1'))
    print(json.dumps(result,indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd());p.add_argument('--data-root',type=Path,required=True);p.add_argument('--reports',type=Path,default=Path('reports/final_pipeline_audit'))
    args=p.parse_args()
    if args.data_root.resolve().is_relative_to(args.project_root.resolve()):p.error('Data root must be external')
    build(args.project_root,args.data_root,args.reports)


if __name__=='__main__':main()
