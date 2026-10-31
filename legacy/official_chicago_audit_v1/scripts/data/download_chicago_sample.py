"""Download a bounded official Chicago Divvy snapshot feasibility sample.

Default: 17 weeks in 2021, at most 50 stations selected from a training-only
anchor poll. Raw downloads remain outside the project. Never export the full
eq45-8inv dataset. TLS verification uses certifi's maintained CA bundle.
"""
from __future__ import annotations
import argparse
import concurrent.futures
from datetime import datetime,timedelta,timezone
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import ssl
import urllib.parse
import urllib.request
import certifi

from download_divvy_data import download as download_object

BASE='https://data.cityofchicago.org'
DATASET='eq45-8inv'
COLUMNS='id,timestamp,station_name,total_docks,docks_in_service,available_docks,available_bikes,status,latitude,longitude,record'


def fetched(url):
    context=ssl.create_default_context(cafile=certifi.where())
    req=urllib.request.Request(url,headers={'User-Agent':'BikeFlowAI-bounded-Chicago-data-audit/1.0','Accept-Encoding':'gzip'})
    with urllib.request.urlopen(req,context=context,timeout=90) as r:
        raw=r.read();headers=dict(r.headers)
        transport_bytes=len(raw)
        if r.headers.get('Content-Encoding','').lower()=='gzip':raw=gzip.decompress(raw)
    return raw,dict(url=url,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),transport_bytes=transport_bytes,etag=headers.get('ETag'),last_modified=headers.get('Last-Modified'))


def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');tmp.replace(path)


def query_url(**params):return BASE+f'/resource/{DATASET}.json?'+urllib.parse.urlencode(params)


class TextParser(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--project-root',type=Path,default=Path.cwd())
    p.add_argument('--max-stations',type=int,default=50)
    p.add_argument('--start',default='2021-05-03T00:00:00')
    p.add_argument('--end',default='2021-08-30T00:00:00')
    p.add_argument('--anchor',default='2021-05-03T00:05:15')
    p.add_argument('--max-records',type=int,default=1000000)
    args=p.parse_args()
    if not 20<=args.max_stations<=50:p.error('This bounded audit requires 20–50 stations')
    root=args.data_root.resolve()
    if root.is_relative_to(args.project_root.resolve()):p.error('Raw storage must be outside the project')
    root.mkdir(parents=True,exist_ok=True)
    start,end=datetime.fromisoformat(args.start),datetime.fromisoformat(args.end)
    if end<=start or end-start>timedelta(weeks=18):p.error('Small audit is capped at 18 weeks')
    if not start<=datetime.fromisoformat(args.anchor)<start+timedelta(weeks=2):p.error('Anchor must be in the first two training weeks')
    manifest_path=root/'download_manifest.json'
    settings=dict(dataset=DATASET,start_local=args.start,end_local_exclusive=args.end,anchor_local=args.anchor,max_stations=args.max_stations,max_records=args.max_records)
    old=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if old and old.get('settings')!=settings:p.error('Use a different data root for different sample settings')
    manifest=dict(settings=settings,source='City of Chicago official historical snapshot dataset',files=[],evidence=[],
        timezone_policy='Floating source timestamps interpreted as America/Chicago; original wall times retained',
        scope='Bounded feasibility audit, not a citywide or entire-2021–2022 audit',download_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    for name,url in [
        ('dataset_metadata.json',BASE+f'/api/views/{DATASET}.json'),
        ('city_data_terms.html','https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html')]:
        raw,meta=fetched(url);path=root/'evidence'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        manifest['evidence'].append(dict(path=path.relative_to(root).as_posix(),**meta))
        if name=='dataset_metadata.json':
            metadata=json.loads(raw);manifest['dataset_metadata']=dict(licenseId=metadata.get('licenseId'),license=metadata.get('license'),
                attribution=metadata.get('attribution'),time_period=metadata.get('metadata',{}).get('custom_fields',{}).get('Metadata',{}).get('Time Period'),rows_updated_at=metadata.get('rowsUpdatedAt'))
        else:
            parser=TextParser();parser.feed(raw.decode());text=' '.join(parser.parts)
            first=text.index('This site provides applications using data that has been modified')
            last=text.index('own risk.',first)+len('own risk.')
            notice=text[first:last].replace('\xa0',' ')
            (root/'evidence/city_required_application_disclaimer.txt').write_text(notice+'\n',encoding='utf-8')
            manifest['city_required_notice_path']='evidence/city_required_application_disclaimer.txt'
    anchor_url=query_url(**{'$select':COLUMNS,'$where':f"timestamp = '{args.anchor}' AND latitude between 41.85 and 41.92 AND longitude between -87.68 and -87.60",'$order':'id','$limit':'2000'})
    anchor_raw,anchor_meta=fetched(anchor_url);anchor=json.loads(anchor_raw)
    candidates=[r for r in anchor if r.get('status')=='In Service' and float(r.get('total_docks','0'))>0]
    candidates.sort(key=lambda x:int(x['id'])) # Python arbitrary precision, never float station IDs.
    cohort=candidates[:args.max_stations]
    if len(cohort)<20:raise ValueError('Training-only anchor has fewer than 20 eligible stations')
    ids=[r['id'] for r in cohort]
    save_json(root/'training_anchor.json',dict(source=anchor_meta,all_anchor_rows=anchor,selected_station_ids=ids,
        rule='First 50 positive-capacity In Service stations by exact integer ID in the predeclared central-Chicago training anchor; no held-out selection'))
    manifest['cohort_station_ids']=ids;manifest['anchor_query']=anchor_meta
    # Single-station equality queries are much cheaper on this historical portal
    # than broad IN-list/time sorts. This changes transport partitioning only.
    manifest['query_partition']='station; four concurrent read-only requests maximum'
    def station_records(station_id):
        offset=0;page=0;records=[]
        while True:
            params={'$select':COLUMNS,'$where':f"timestamp >= '{start.isoformat()}' AND timestamp < '{end.isoformat()}' AND id={int(station_id)}",
                    '$order':'timestamp,id','$limit':'20000','$offset':str(offset)}
            url=query_url(**params);name=f'station_{int(station_id)}_{start:%Y%m%d}_{end:%Y%m%d}_{page:02d}.json.gz';target=root/'raw/snapshots'/name
            cached=next((r for r in old.get('files',[]) if r.get('kind')=='snapshots' and r.get('url')==url),None)
            if cached and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==cached.get('saved_sha256'):
                record=cached;count=record['rows']
            else:
                raw,meta=fetched(url);rows=json.loads(raw)
                if not isinstance(rows,list):raise ValueError(f'API did not return rows: {rows}')
                count=len(rows)
                if any(str(r['id'])!=station_id for r in rows):raise ValueError('Socrata result escaped bounded station cohort')
                target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_suffix('.gz.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(target)
                record=dict(kind='snapshots',path=target.relative_to(root).as_posix(),rows=count,
                    station_id=station_id,start_local=start.isoformat(),end_local_exclusive=end.isoformat(),saved_bytes=target.stat().st_size,
                    saved_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),**meta)
            records.append(record)
            if count<20000:break
            offset+=count;page+=1
        return station_id,records
    total=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        jobs=[executor.submit(station_records,station_id) for station_id in ids]
        for job in concurrent.futures.as_completed(jobs):
            station_id,records=job.result();n=sum(r['rows'] for r in records);total+=n
            if total>args.max_records:raise ValueError('Small-audit row cap exceeded; no complete manifest written')
            manifest['files'].extend(records);save_json(manifest_path,manifest)
            print(f"Snapshot station {station_id}: {n:,} rows; total {total:,}",flush=True)
    manifest['files'].sort(key=lambda r:(int(r['station_id']),r['url']))
    month_start=start.replace(day=1)
    months=[]
    while month_start<end:
        months.append(month_start.strftime('%Y%m'))
        month_start=(month_start.replace(year=month_start.year+1,month=1) if month_start.month==12 else month_start.replace(month=month_start.month+1))
    for month in months:
        url=f'https://divvy-tripdata.s3.amazonaws.com/{month}-divvy-tripdata.zip'
        path=root/'raw/trips'/f'{month}-divvy-tripdata.zip'
        record=download_object(url,path)
        manifest['files'].append(dict(kind='trips',month=month,path=path.relative_to(root).as_posix(),**record))
        save_json(manifest_path,manifest)
    manifest.update(completed_at_utc=datetime.now(timezone.utc).isoformat(),snapshot_rows=total,
        actual_station_count=len(ids),compressed_snapshot_bytes=sum(r.get('saved_bytes',0) for r in manifest['files'] if r['kind']=='snapshots'),
        trip_zip_bytes=sum(r.get('bytes',0) for r in manifest['files'] if r['kind']=='trips'))
    save_json(manifest_path,manifest)
    print(json.dumps({k:manifest[k] for k in ['snapshot_rows','actual_station_count','compressed_snapshot_bytes','trip_zip_bytes','completed_at_utc']},indent=2),flush=True)


if __name__=='__main__':main()
