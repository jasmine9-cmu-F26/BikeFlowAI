"""Bounded Open-Meteo forecast audit; coverage is not issuance-time evidence.

All raw responses/evidence stay outside the checkout. No ERA5 data is requested.
The frozen Divvy cohort/protocol is read-only. No model training is performed.
"""
from __future__ import annotations
import argparse
import bisect
import csv
from datetime import datetime,timedelta,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request

import certifi
import duckdb
import numpy as np
import pyarrow as pa

CORE=['temperature_2m','relative_humidity_2m','precipitation','wind_speed_10m','weather_code']
EXTRA=['apparent_temperature','cloud_cover','precipitation_probability']
# Stable request order permits verification/reuse of already fetched responses.
VARIABLES=['temperature_2m','relative_humidity_2m','precipitation','wind_speed_10m','apparent_temperature','weather_code','cloud_cover','precipitation_probability']
MODELS=['gfs_global','gfs_seamless','gfs_hrrr','best_match']
SOURCES={
    'historical_forecast':'https://open-meteo.com/en/docs/historical-forecast-api',
    'live_forecast':'https://open-meteo.com/en/docs',
    'home':'https://open-meteo.com/',
    'single_runs':'https://open-meteo.com/en/docs/single-runs-api',
    'historical_weather_reanalysis':'https://open-meteo.com/en/docs/historical-weather-api',
    'licence':'https://open-meteo.com/en/licence',
    'terms':'https://open-meteo.com/en/terms'}


def iso(epoch):return datetime.fromtimestamp(int(epoch),timezone.utc).isoformat().replace('+00:00','Z')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n');tmp.replace(path)
def rows(path):
    with path.open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))
def write_csv(path,values,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or list(values[0]));writer.writeheader();writer.writerows(values)


def get(url,path,reuse=True):
    sidecar=path.with_suffix(path.suffix+'.source.json')
    if reuse and path.exists() and sidecar.exists():
        info=read(sidecar)
        if info['url']==url and info['sha256']==sha(path):return info
    requested=datetime.now(timezone.utc).isoformat()
    context=ssl.create_default_context(cafile=certifi.where())
    req=urllib.request.Request(url,headers={'User-Agent':'BikeFlowAI-noncommercial-weather-audit/1.0','Accept-Encoding':'gzip'})
    try:
        with urllib.request.urlopen(req,context=context,timeout=90) as response:
            raw=response.read();status=response.status;headers=dict(response.headers)
            if response.headers.get('Content-Encoding','').lower()=='gzip':raw=gzip.decompress(raw)
    except urllib.error.HTTPError as error:
        raw=error.read();status=error.code;headers=dict(error.headers)
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.part')
    tmp.write_bytes(gzip.compress(raw,mtime=0) if path.name.endswith('.gz') else raw);tmp.replace(path)
    info=dict(url=url,http_status=status,requested_at_utc=requested,received_at_utc=datetime.now(timezone.utc).isoformat(),
        sha256=sha(path),raw_sha256=hashlib.sha256(raw).hexdigest(),saved_bytes=path.stat().st_size,
        etag=headers.get('ETag'),last_modified=headers.get('Last-Modified'))
    write_json(sidecar,info);return info


def date_parts(start,end):
    current=start
    while current<=end:
        nextmonth=(current.replace(day=28)+timedelta(days=4)).replace(day=1)
        last=min(end,nextmonth-timedelta(days=1))
        yield current.strftime('%Y-%m-%d'),last.strftime('%Y-%m-%d')
        current=nextmonth


def download(project,root,protocol):
    if root.resolve().is_relative_to(project.resolve()):raise ValueError('Weather data root must be outside project')
    root.mkdir(parents=True,exist_ok=True)
    cohort=rows(project/protocol['cohort_manifest'])
    latitude=round(float(np.median([float(r['historical_lat']) for r in cohort])),6)
    longitude=round(float(np.median([float(r['historical_lon']) for r in cohort])),6)
    start=datetime.fromisoformat(protocol['chronological_splits'][0]['start_utc'].replace('Z','+00:00'))
    end=datetime.fromisoformat(protocol['chronological_splits'][-1]['end_utc_exclusive'].replace('Z','+00:00'))
    common=dict(latitude=latitude,longitude=longitude,hourly=','.join(VARIABLES),timezone='GMT',timeformat='unixtime',
        temperature_unit='celsius',wind_speed_unit='ms',precipitation_unit='mm')
    manifest=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),collector_script_sha256=sha(Path(__file__)),
        study_start_utc=iso(start.timestamp()),study_end_utc_exclusive=iso(end.timestamp()),
        weather_location=dict(latitude=latitude,longitude=longitude,selection='Median historical coordinates of fixed app32 cohort; one common weather location, not 32 station-specific queries'),
        core_variables=CORE,diagnostic_variables=EXTRA,models=MODELS,files=[],evidence=[],ERA5_requested=False,
        protocol_sha256=sha(project/'data/manifests/chicago/app32/data_protocol.json'))
    for label,url in SOURCES.items():
        path=root/'evidence'/(label+'.html.gz');info=get(url,path)
        manifest['evidence'].append(dict(name=label,path=path.relative_to(root).as_posix(),**info))
    first=start.date()-timedelta(days=1)
    for model in MODELS:
        for lo,hi in date_parts(first,end.date()):
            params=dict(common,models=model,start_date=lo,end_date=hi)
            url='https://historical-forecast-api.open-meteo.com/v1/forecast?'+urllib.parse.urlencode(params)
            path=root/'raw/historical'/model/(lo+'_'+hi+'.json.gz');info=get(url,path)
            manifest['files'].append(dict(kind='historical_forecast',model=model,start_date=lo,end_date=hi,path=path.relative_to(root).as_posix(),**info))
            write_json(root/'download_manifest.json',manifest)
            print(f'Historical forecast {model} {lo}..{hi}: HTTP {info["http_status"]}',flush=True)
        url='https://api.open-meteo.com/v1/forecast?'+urllib.parse.urlencode(dict(common,models=model,forecast_days=2))
        path=root/'raw/live'/(model+'.json.gz');info=get(url,path)
        manifest['files'].append(dict(kind='live_forecast_schema_control',model=model,path=path.relative_to(root).as_posix(),**info))
        write_json(root/'download_manifest.json',manifest)
    manifest['completed_at_utc']=datetime.now(timezone.utc).isoformat();write_json(root/'download_manifest.json',manifest)
    return manifest


def summarize_hourly(document,start,end):
    hourly=document.get('hourly',{});times=hourly.get('time',[])
    if any(not isinstance(t,int) for t in times):raise ValueError('Expected UTC Unix integer timestamps')
    if any(t%3600 for t in times):raise ValueError('Expected weather timestamps on UTC hour boundaries')
    if any(b<=a for a,b in zip(times[:-1],times[1:])):raise ValueError('Duplicate or unsorted weather timestamps')
    for variable in VARIABLES:
        if variable in hourly and len(hourly[variable])!=len(times):raise ValueError('Mismatched hourly variable length')
    selected=[i for i,t in enumerate(times) if start<=t<end]
    expected=math.ceil(end/3600)-math.ceil(start/3600)
    result=[]
    for variable in VARIABLES:
        values=hourly.get(variable,[None]*len(times))
        valid=[values[i] for i in selected if isinstance(values[i],(float,int)) and math.isfinite(values[i])]
        missing=expected-len(valid)
        result.append(dict(variable=variable,role='core_candidate' if variable in CORE else 'diagnostic',expected_hours=expected,
            returned_study_timestamps=len(selected),nonmissing_hours=len(valid),missing_hours=missing,missing_fraction=missing/expected if expected else None,
            minimum=min(valid) if valid else None,maximum=max(valid) if valid else None,unit=document.get('hourly_units',{}).get(variable)))
    return result


def candidate_indices(times,requests,max_age=3600):
    times=np.asarray(times,dtype=np.int64);requests=np.asarray(requests,dtype=np.int64)
    indices=np.searchsorted(times,requests,side='right')-1
    if not len(times):return np.full(len(requests),-1,dtype=np.int64)
    safe=indices.clip(0,len(times)-1)
    return np.where((indices>=0)&(requests-times[safe]<=max_age),indices,-1)


def causal_run_index(runs,request_time,target_time):
    """A valid-time row alone cannot satisfy the issuance/availability gate."""
    eligible=[(i,r) for i,r in enumerate(runs) if r.get('valid_time')==target_time and
        r.get('issued_at') is not None and r.get('available_at') is not None and
        r['issued_at']<=r['available_at']<=request_time]
    return max(eligible,key=lambda pair:pair[1]['available_at'])[0] if eligible else -1


def audit(project,root,out,protocol):
    manifest=read(root/'download_manifest.json')
    for f in manifest['files']+manifest['evidence']:
        if sha(root/f['path'])!=f['sha256']:raise ValueError('Source response hash mismatch')
    start=int(datetime.fromisoformat(manifest['study_start_utc'].replace('Z','+00:00')).timestamp())
    end=int(datetime.fromisoformat(manifest['study_end_utc_exclusive'].replace('Z','+00:00')).timestamp())
    out.mkdir(parents=True,exist_ok=True)
    cohort={r['station_id'] for r in rows(project/protocol['cohort_manifest'])}
    snapshots=root.parent/'chicago_historical_2021_sample/processed/snapshots.parquet'
    con=duckdb.connect()
    table=con.sql('SELECT station_id,timestamp FROM read_parquet(?) WHERE timestamp>=? AND timestamp<? ORDER BY station_id,timestamp',params=[str(snapshots),start,end]).to_arrow_table()
    source=table.to_pydict();mask=np.array([sid in cohort for sid in source['station_id']]);stationids=np.array(source['station_id'])[mask];requests=np.array(source['timestamp'],dtype=np.int64)[mask]
    documents={};missingness=[];monthly=[];joins=[];stationjoins=[];schemas=[];timequality=[];quality=[]
    allcorepass=True
    for model in MODELS:
        parts=[]
        for f in manifest['files']:
            if f['kind']!='historical_forecast' or f['model']!=model:continue
            doc=json.loads(gzip.decompress((root/f['path']).read_bytes()))
            if f['http_status']!=200 or 'hourly' not in doc:raise ValueError(f'Historical forecast failed: {model} {doc}')
            parts.append(doc)
            lo=max(start,int(datetime.fromisoformat(f['start_date']).replace(tzinfo=timezone.utc).timestamp()))
            hi=min(end,int((datetime.fromisoformat(f['end_date'])+timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp()))
            monthly.extend(dict(model=model,month=f['start_date'][:7],**r) for r in summarize_hourly(doc,lo,hi))
        combined=dict(parts[0]);combined['hourly']={key:sum((p['hourly'].get(key,[None]*len(p['hourly']['time'])) for p in parts),[]) for key in ['time']+VARIABLES}
        documents[model]=combined
        stats=summarize_hourly(combined,start,end);missingness.extend(dict(model=model,**r) for r in stats)
        for variable,lo,hi in [('relative_humidity_2m',0,100),('cloud_cover',0,100),('precipitation_probability',0,100),('wind_speed_10m',0,None),('precipitation',0,None)]:
            bad=[i for i,t in enumerate(combined['hourly']['time']) if start<=t<end and combined['hourly'][variable][i] is not None and
                 (combined['hourly'][variable][i]<lo or (hi is not None and combined['hourly'][variable][i]>hi))]
            quality.append(dict(model=model,variable=variable,lower_bound=lo,upper_bound=hi,out_of_range_hours=len(bad),policy='Reported, not clipped or treated as empty; review before adding feature'))
        times=np.array(combined['hourly']['time'],dtype=np.int64);within=times[(times>=start)&(times<end)]
        timequality.append(dict(model=model,returned_study_hours=len(within),expected_study_hours=(end-start)//3600,
            median_interval_seconds=float(np.median(np.diff(within))),p90_interval_seconds=float(np.quantile(np.diff(within),.9)),
            UTC_offset_seconds=combined['utc_offset_seconds'],timezone=combined['timezone'],
            first_study_time_utc=iso(within[0]),last_study_time_utc=iso(within[-1]),
            run_issue_time_present=any(k in combined for k in ['issued_at','run','initialisation_time','available_at']),
            generationtime_ms_is_issue_time=False))
        livef=next(f for f in manifest['files'] if f['kind']=='live_forecast_schema_control' and f['model']==model)
        live=json.loads(gzip.decompress((root/livef['path']).read_bytes()))
        for variable in VARIABLES:
            schemas.append(dict(model=model,variable=variable,historical_key_present=variable in combined['hourly'],live_key_present=variable in live.get('hourly',{}),
                historical_unit=combined.get('hourly_units',{}).get(variable),live_unit=live.get('hourly_units',{}).get(variable),
                units_equal=combined.get('hourly_units',{}).get(variable)==live.get('hourly_units',{}).get(variable),
                live_nonmissing=sum(v is not None for v in live.get('hourly',{}).get(variable,[]))))
        allcorepass=allcorepass and all(r['missing_fraction']<=.01 for r in stats if r['variable'] in CORE)
        indices=candidate_indices(times,requests);safe=indices.clip(0,len(times)-1)
        corevalid=np.ones(len(times),dtype=bool)
        for variable in CORE:
            corevalid &= np.array([isinstance(v,(float,int)) and math.isfinite(v) for v in combined['hourly'][variable]])
        hits=(indices>=0)&corevalid[safe]
        groups=[dict(split='sample',start_utc=manifest['study_start_utc'],end_utc_exclusive=manifest['study_end_utc_exclusive'])]+protocol['chronological_splits']
        for scope in groups:
            lo=int(datetime.fromisoformat(scope['start_utc'].replace('Z','+00:00')).timestamp());hi=int(datetime.fromisoformat(scope['end_utc_exclusive'].replace('Z','+00:00')).timestamp())
            inside=(requests>=lo)&(requests<hi);count=int(inside.sum());kept=int((inside&hits).sum())
            joins.append(dict(model=model,split=scope['split'],station_snapshot_rows=count,backward_valid_time_joined_core_rows=kept,
                valid_time_join_rate=kept/count if count else 0,maximum_join_age_seconds=int((requests[inside&hits]-times[safe[inside&hits]]).max()) if kept else None,
                certified_request_time_available_rows=0,availability_status='NOT_CERTIFIABLE_MISSING_ISSUE_AND_PUBLICATION_TIMES',
                join_interpretation='Calendar alignment only; valid_time <= request_time is not forecast available_at <= request_time'))
        for sid in sorted(cohort):
            inside=stationids==sid;count=int(inside.sum());kept=int((inside&hits).sum())
            stationjoins.append(dict(model=model,station_id=sid,snapshot_rows=count,backward_valid_time_core_rows=kept,valid_time_join_rate=kept/count if count else 0,certified_causal_rows=0))
        # Local normalized table explicitly carries null issuance/availability.
        weather=pa.Table.from_pylist([dict(valid_time=int(t),issued_at=None,available_at=None,model=model,**{v:combined['hourly'][v][i] for v in VARIABLES}) for i,t in enumerate(times)])
        con.register('weather',weather)
        processed=root/'processed';processed.mkdir(exist_ok=True)
        con.execute('COPY weather TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(processed/(model+'.parquet'))])
    con.close()
    write_csv(out/'missingness_by_variable.csv',missingness);write_csv(out/'missingness_by_month.csv',monthly)
    write_csv(out/'timestamp_quality.csv',timequality);write_csv(out/'schema_alignment.csv',schemas)
    write_csv(out/'snapshot_join_summary.csv',joins);write_csv(out/'join_coverage_by_station.csv',stationjoins)
    write_csv(out/'value_quality.csv',quality)
    comparisons=[]
    for i,a in enumerate(MODELS):
        for b in MODELS[i+1:]:
            left=documents[a]['hourly'];right=documents[b]['hourly']
            comparisons.append(dict(requested_model_a=a,requested_model_b=b,time_arrays_equal=left['time']==right['time'],
                all_requested_variable_arrays_equal=all(left[v]==right[v] for v in VARIABLES),
                interpretation='Requested aliases/blends can share an effective model; identical arrays do not prove independent archives'))
    write_csv(out/'requested_model_comparison.csv',comparisons)
    summary=dict(decision='NEED_TO_RESTRICT_NOT_REQUIRED',weather_required=False,
        data_coverage_status='PASS_CORE_CANDIDATE_VARIABLES' if allcorepass else 'NEED_TO_RESTRICT_MODEL_OR_VARIABLES',
        causal_availability_status='NOT_CERTIFIABLE_FROM_STITCHED_HOURLY_ARCHIVE',
        study_start_utc=manifest['study_start_utc'],study_end_utc_exclusive=manifest['study_end_utc_exclusive'],
        study_hours=(end-start)//3600,stations=len(cohort),station_snapshot_rows=len(requests),
        core_variables=CORE,diagnostic_variables=EXTRA,core_variable_definition='Five variables enumerated in the latest supplied proposal (3): temperature, precipitation amount, wind speed, relative humidity and weather code',
        models=MODELS,preferred_model_candidate='gfs_global (explicit requested model, not retrospective best_match blend)',
        model_column_meaning='Requested API model ID; response does not expose original per-row model/run/issue lineage. Seamless/Best Match can share effective model output.',
        diagnostic_missing_threshold=.01,weather_location=manifest['weather_location'],
        ERA5_requested=False,no_reanalysis_substitution=True,source_data_license='CC-BY-4.0',free_API_access='Noncommercial use within service limits; separate from data reuse license',
        important_distinctions=['Valid time is not issuance/available-at time','A stitched t+60 weather row may use a run published after request t','generationtime_ms is response generation duration, not forecast run metadata','An arbitrary backward shift is not proof of historical forecast availability','No station/model/split changes or feature training performed'],
        timestamp_joins=joins,variable_results=missingness,value_quality=quality,download_manifest_sha256=sha(root/'download_manifest.json'),
        audit_script_sha256=sha(Path(__file__)),historical_protocol_sha256=sha(project/'data/manifests/chicago/app32/data_protocol.json'),
        required_feature_gate=dict(core_coverage=allcorepass,forecast_issue_and_publication_provenance=False,pass_all=False),
        recommended_next_step='Keep weather optional/excluded in causal 2021 baseline; require issue-aware run archive or explicitly restricted supplementary weather experiment before changing required status')
    write_json(out/'audit_summary.json',summary);write_json(out/'download_manifest.json',manifest)
    write_json(out/'source_inventory.json',dict(urls=SOURCES,data_license='https://creativecommons.org/licenses/by/4.0/',attribution='Weather data by Open-Meteo.com; normalized hourly data and joins by BikeFlow AI',free_api_noncommercial_only=True))
    report=f'''# Open-Meteo weather audit: bounded 2021 Chicago cohort

**{summary['decision']}**. Coverage and time-of-availability are separate gates. Weather remains **optional / excluded from the certified causal baseline**; this audit does not promote it to required.

## Source, scope and licence

Preferred candidate: [9] [Historical Forecast API]({SOURCES['historical_forecast']}); live schema and source: [10] [Open-Meteo Forecast API and data licence]({SOURCES['home']}). Maskable PPO moves to [11] in the proposal reference update.

The fixed app32 historical window is 2021-05-03 00:00 through 2021-08-30 00:00 America/Chicago (exclusive), {summary['study_hours']:,} hours, {len(requests):,} recorded station snapshots. UTC/Unix requests include a preceding context day. One weather point at median historical app-station coordinates is used; this does not audit spatial variation at every station.

Explicit GFS Global, GFS Seamless and HRRR models plus Best Match diagnostic were fetched by month, not the full weather archive. Model columns record requested API IDs, not confirmed per-row run lineage; Seamless and Best Match may share an effective model. A present-day two-day live forecast control checks keys/units only; it is not evidence of 2021 information availability. Documentation, raw JSON, URLs, HTTP status, hashes and local processed Parquet are external to Git. Exact provenance is in download_manifest.json.

Weather data by [Open-Meteo.com]({SOURCES['home']}) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): attribution, licence link and indication of transformations are required. Free API access is independently limited to noncommercial use and published request quotas; commercial data reuse rights do not make the free API commercial service access free. No upstream AGPL server code was copied. See [licence]({SOURCES['licence']}) and [terms]({SOURCES['terms']}).

## Missingness and schema

The latest proposal enumerates five weather features: temperature_2m, relative_humidity_2m, precipitation amount, wind_speed_10m and weather_code. Apparent temperature, cloud cover and precipitation probability are separate diagnostics; do not silently replace probability with precipitation amount. Per-variable and per-month counts include missing timestamps in the denominator. Threshold <=1% is a source-feasibility diagnostic, not a trained-model acceptance rule.

| Model | Variable | Missing hours / expected | Missing % |
|---|---|---:|---:|
'''
    report+='\n'.join(f"| {r['model']} | {r['variable']} | {r['missing_hours']} / {r['expected_hours']} | {r['missing_fraction']:.2%} |" for r in missingness)
    report+='''

See missingness_by_variable.csv, missingness_by_month.csv, timestamp_quality.csv and schema_alignment.csv. Hourly keys/units do not prove identical numerical models between 2021 and current forecasts. Model versions, spatial resolution and current availability can change. Wind is requested in m/s, temperature °C and precipitation mm. Precipitation is a preceding-hour total, not a probability.

Use the explicit GFS Global control to review any missing weather-code hours and core calendar-join exclusions. Precipitation probability is a separate diagnostic, not an interchangeable precipitation-amount field. Out-of-range values are reported in value_quality.csv without clipping. Requested aliases that return identical arrays (requested_model_comparison.csv) must not be counted as independent model-replication evidence.

## Temporal alignment versus causal availability

Hourly UTC valid times can be matched backward to snapshot request times with a <=1-hour age bound. This diagnostic never nearest-matches a future valid time and does not interpolate across missing hours. It is **calendar alignment only**, not an authorization to use the result as a feature. See snapshot_join_summary.csv and join_coverage_by_station.csv for all fixed splits and each of 32 stations.

Historical Forecast stitches early forecast hours from successive runs. The responses tested expose hourly valid times, not per-row issued_at / published_at / available_at. generationtime_ms is API processing duration. A row with valid_time <= request_time does not imply its originating run was already published at request time. Likewise a t+h row may come from a newer run than the t request could have seen.

Thus certified request-time-available joins are **unknown/not certifiable**, not a measured 100% and not evidence that every forecast was actually late. Synthetic issuance-gate tests reject rows without available_at and reject runs published after request, even when their initialization or valid time is earlier. Do not fabricate issuance metadata by flooring, delaying one hour or subtracting a model-cycle length.

The [Single Runs API](https://open-meteo.com/en/docs/single-runs-api) preserves initialization/run structure but currently documents later archive starts (IFS from March 2024, other models from April 2026), so it does not automatically solve this 2021 cohort. Initialization alone also needs a defensible publication/ingestion delay. The generic Historical Forecast page contains broad 2022 coverage text while its model table lists earlier GFS/HRRR starts; actual responses, pinned model IDs and per-variable results are used here.

ERA5/reanalysis was **not downloaded or substituted** as primary features. It is valid as a separately labeled retrospective-weather analysis, not as proof of what a request-time forecaster knew.

## Decision and next work

Keep the current historical period, app cohort and frozen model protocol unchanged. Freeze an exact subset/model only after all feature variables and issuance/publication semantics pass. Until then the causal baseline omits weather; a stitched-archive weather ablation must be explicitly labeled with its unverified availability assumption, not presented as leakage-free causal replay.

For future current-data use, archive the live forecast response at receipt time and keep forecast_received_at <= request_time plus valid_time near ETA. That establishes a prospective provenance trail; it cannot retroactively repair 2021. This audit does not silently add weather calls to the running GBFS collector or use its quotas.
'''
    (out/'weather_audit.md').write_text(report,encoding='utf-8',newline='\n')
    print(json.dumps({k:summary[k] for k in ['decision','data_coverage_status','causal_availability_status','study_hours','station_snapshot_rows','weather_required']},indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path.cwd());p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--reports',type=Path,default=Path('reports/weather_audit'));p.add_argument('--offline',action='store_true')
    args=p.parse_args();project=args.project_root.resolve();root=args.data_root.resolve()
    if root.is_relative_to(project):p.error('Raw weather data must stay outside project')
    protocol=read(project/'data/manifests/chicago/app32/data_protocol.json')
    if not args.offline:download(project,root,protocol)
    audit(project,root,args.reports,protocol)


if __name__=='__main__':main()
