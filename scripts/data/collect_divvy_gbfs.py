"""Capture complete official Divvy station_status polls with success/error heartbeats.

Run --once from Task Scheduler every 120 seconds, or use --interval-seconds
for a foreground loop. Identical inventories are deliberately NOT suppressed.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request
import uuid

DISCOVERY='https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json'
ALLOWED_HOSTS={'gbfs.divvybikes.com','gbfs.lyft.com'}


def now():return datetime.now(timezone.utc).isoformat()


def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');tmp.replace(path)


@contextmanager
def capture_lock(root):
    path=root/'collector.lock';path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('a+b');f.seek(0)
    if path.stat().st_size==0:f.write(b'0');f.flush()
    locked=False
    try:
        try:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except (BlockingIOError,PermissionError):
            yield False
            return
        yield True
    finally:
        if locked:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()


def fetch(url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError('Collector only follows official Divvy/Lyft HTTPS GBFS endpoints')
    requested=now();start=time.monotonic()
    req=urllib.request.Request(url,headers={'User-Agent':'BikeFlowAI-full-snapshot-collector/1.0'})
    with urllib.request.urlopen(req,timeout=20) as r:
        data=r.read();document=json.loads(data)
    return document,data,dict(url=url,requested_at_utc=requested,received_at_utc=now(),
        latency_seconds=time.monotonic()-start,sha256=hashlib.sha256(data).hexdigest())


def save_gzip(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_bytes(gzip.compress(data,mtime=0));tmp.replace(path)


def capture(data_root,stop_at=None):
    root=Path(data_root).resolve()/'current_validation'
    root.mkdir(parents=True,exist_ok=True)
    if stop_at and datetime.now(timezone.utc)>=datetime.fromisoformat(stop_at.replace('Z','+00:00')):
        return dict(status='finished',reason='Configured project collection end reached')
    with capture_lock(root) as locked:
        if not locked:return dict(status='already_running')
        state_path=root/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {}
        record=dict(started_at_utc=now(),record_type='full_poll',
            collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        try:
            if not state.get('feeds') or time.time()-state.get('discovered_epoch',0)>86400:
                discovery,raw,meta=fetch(DISCOVERY)
                feeds={x['name']:x['url'] for x in discovery['data']['en']['feeds']}
                state.update(feeds=feeds,discovered_epoch=time.time())
                save_gzip(root/'discovery'/f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json.gz",raw)
            # Metadata is fetched before the status, so it is known at the poll's
            # request/receipt time. Only its content is deduplicated, never polls.
            information,raw_info,info_meta=fetch(state['feeds']['station_information'])
            stations=information['data']['stations']
            canonical=json.dumps(sorted(stations,key=lambda s:str(s['station_id'])),sort_keys=True,separators=(',',':')).encode()
            version=hashlib.sha256(canonical).hexdigest()
            metadata_path=root/'metadata'/(version+'.json.gz')
            if not metadata_path.exists():save_gzip(metadata_path,raw_info)
            status,raw,status_meta=fetch(state['feeds']['station_status'])
            values=status['data']['stations']
            ids=[str(x['station_id']) for x in values]
            if not values or len(ids)!=len(set(ids)):
                raise ValueError('Empty or duplicate-ID full station status response')
            stamp=datetime.now(timezone.utc)
            target=root/'status'/f'{stamp:%Y/%m/%d}'/(f'{stamp:%Y%m%dT%H%M%S%fZ}_'+uuid.uuid4().hex[:8]+'.json.gz')
            save_gzip(target,raw)
            record.update(status='ok',station_count=len(values),snapshot_path=target.relative_to(root).as_posix(),
                metadata_path=metadata_path.relative_to(root).as_posix(),metadata_content_sha256=version,
                metadata_capture=info_meta,status_capture=status_meta,feed_last_updated=status.get('last_updated'),
                feed_ttl=status.get('ttl'),feed_version=status.get('version'),
                is_full_status_poll=True,unchanged_inventory_suppressed=False,
                stale_feed_over_5min=isinstance(status.get('last_updated'),(int,float)) and time.time()-status['last_updated']>300)
            if not state.get('system_information'):
                try:
                    system,system_raw,system_meta=fetch(state['feeds']['system_information'])
                    state['system_information']=system
                    save_gzip(root/'system_information.json.gz',system_raw)
                except Exception as exc:record['system_information_error']=f'{type(exc).__name__}: {exc}'
            state.update(last_success_utc=record['status_capture']['received_at_utc'],last_snapshot=record['snapshot_path'],
                successful_polls=state.get('successful_polls',0)+1,metadata_content_sha256=version)
        except Exception as exc:
            record.update(status='error',error=f'{type(exc).__name__}: {exc}')
            state['failed_polls']=state.get('failed_polls',0)+1
        record['finished_at_utc']=now()
        with (root/'polls.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(record)+'\n');f.flush();os.fsync(f.fileno())
        atomic_json(root/'last_poll.json',record);atomic_json(state_path,state)
        return record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--once',action='store_true')
    p.add_argument('--interval-seconds',type=int,default=120)
    p.add_argument('--stop-at',default='2026-12-13T07:59:00+00:00')
    args=p.parse_args()
    if args.interval_seconds<60:p.error('Interval must be >=60 seconds')
    while True:
        before=time.monotonic();record=capture(args.data_root,args.stop_at)
        if sys.stdout is not None:print(json.dumps(record),flush=True)
        if args.once or record['status']=='finished':break
        time.sleep(max(1,args.interval_seconds-(time.monotonic()-before)))


if __name__=='__main__':main()
