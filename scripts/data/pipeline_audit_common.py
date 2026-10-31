"""Shared deterministic helpers for the fixed-cohort final pipeline audits."""
import csv,hashlib,json,math
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def epoch(value):return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp())
def iso(value):return datetime.fromtimestamp(int(value),timezone.utc).isoformat().replace('+00:00','Z')
def csvrows(path):
    with Path(path).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')
def write_csv(path,rows,fields=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);rows=list(rows)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def splits(protocol):return [dict(name=s['split'],lo=epoch(s['start_utc']),hi=epoch(s['end_utc_exclusive'])) for s in protocol['chronological_splits']]
def split_at(value,scopes):return next((s['name'] for s in scopes if s['lo']<=value<s['hi']),None)
def asof_indices(times,requests,max_age):
    times=np.asarray(times,dtype=np.int64);requests=np.asarray(requests,dtype=np.int64)
    if not len(times):return np.full(len(requests),-1,dtype=np.int64)
    ix=np.searchsorted(times,requests,side='right')-1;safe=ix.clip(0,len(times)-1)
    return np.where((ix>=0)&(requests-times[safe]<=max_age),ix,-1)
def distance_m(lat1,lon1,lat2,lon2):
    return np.hypot((np.asarray(lat1)-lat2)*111320,(np.asarray(lon1)-lon2)*111320*np.cos(np.deg2rad(lat2)))
def haversine_m(lat1,lon1,lat2,lon2):
    a,b,c,d=map(math.radians,[lat1,lon1,lat2,lon2]);v=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371008.8*2*math.asin(min(1,math.sqrt(v)))
def final_contract(project):
    project=Path(project);protocol=read(project/'data/manifests/chicago/app32/data_protocol.json')
    return dict(version=1,status='audited_feature_table_contract',base_protocol_sha256=sha(project/'data/manifests/chicago/app32/data_protocol.json'),
        cohort_sha256=protocol['cohort_sha256'],horizons_minutes=protocol['horizons_minutes'],chronological_splits=protocol['chronological_splits'],
        feature_request_grid=dict(interval_seconds=600,phase_seconds=360,phase_source='Frozen original app32 audit, learned from training only'),
        live_freshness_seconds=300,replay_freshness_seconds=900,lag_minutes=[10,30,60],lag_asof_max_age_seconds=900,
        live_freshness_definition='Serving cache receipt age and provider feed last_updated age must each be <=300s when present; this is a serving contract, not a claim that the five-minute validation collector implements a live cache',
        lag_policy='Latest valid snapshot <= request_time-lag; never nearest future; missing lags remain native NaN with flags',
        feature_metadata_policy='Capacity/coordinates/service metadata taken from the exact causal base snapshot, not future station-map intervals or 2026 metadata',
        label_policy=protocol['label_matching'],label_task='Bike/dock unavailability; known closed target is unavailable; missing target excluded',
        base_policy='Known valid and In Service causal base; no label peeking in feature builder',
        B2=dict(cell=['station_id','weekday','hour'],minimum_cell_observations=20,source='valid training snapshots only',
            sparse_cell_fallback='Station overall rate from same fit period',held_out_fit='All train before train end',training_replay_fit='Only prior complete training weeks; first week has no B2 and requires B1 fallback'),
        OD=dict(minimum_training_trips=20,duration_seconds=[60,21600],both_trip_times_in_training=True,
            fallback='1.3 * haversine_distance_m / 4 m/s, as proposal; zero-distance self pairs retained and flagged'),
        weather='Excluded: historical issue/publication provenance remains unresolved',
        split_roles=dict(train='Forecaster fit and future policy training pool',tune='Hyperparameters and planner/policy development',calibration='Final probability calibration only',test='Final held-out evaluation'),
        policy_split='No fifth chronological policy partition; any policy training uses train-only out-of-fold forecaster predictions, not supplied by this feature audit',
        limits=['Recorded source timestamps stand in for unmeasured historical publication latency','Prospective 2026 identity filter is external deployment scope, not test-label selection','Feature-table audit is not model or replay-policy performance validation'])
