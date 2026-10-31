"""Time matching and Chicago timezone utilities, independent of legacy sources."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import bisect
import numpy as np

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

def norm_name(value):
    return ' '.join(str(value or '').casefold().split())

def classify_local(value,zone_name='America/Chicago'):
    zone=ZoneInfo(zone_name);possibilities=set()
    for fold in (0,1):
        utc=value.replace(tzinfo=zone,fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None)==value:
            possibilities.add(utc)
    if not possibilities:return 'nonexistent',None
    if len(possibilities)>1:return 'ambiguous',None
    return 'unique',next(iter(possibilities))

def dst_intervals(start,end):
    # IANA ZoneInfo is authoritative; do not hard-code US DST dates or offsets.
    intervals=[];current=start;active=None
    while current<end:
        status,_=classify_local(current)
        if status!='unique':
            if active is None:active=[current,current+timedelta(minutes=30),status]
            elif active[2]==status:active[1]=current+timedelta(minutes=30)
            else:intervals.append(active);active=[current,current+timedelta(minutes=30),status]
        elif active is not None:intervals.append(active);active=None
        current+=timedelta(minutes=30)
    if active is not None:intervals.append(active)
    return intervals


def asof_index(times,decision_time,max_age_seconds=900):
    """Latest recorded observation <= decision time; stale/missing returns -1.

    Times must be sorted. This uses recorded source time, not independently
    measured historical publication/ingestion latency.
    """
    if max_age_seconds < 0:
        raise ValueError('max_age_seconds must be nonnegative')
    i=bisect.bisect_right(times,decision_time)-1
    return i if i>=0 and decision_time-times[i]<=max_age_seconds else -1
