"""Audit official Divvy trip overlap, conservative endpoint mapping, and OD times.

Raw CSVs, point-level joins, and full OD tables stay outside the repository.
America/Chicago DST folds/gaps are excluded explicitly, never guessed.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo
import zipfile
import duckdb


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


def write_csv(path,rows,fields=None):
    rows=list(rows);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)


def annotate_local_times_sql():
    return '''CREATE OR REPLACE TEMP TABLE times AS SELECT p.*,
        EXISTS(SELECT 1 FROM bad_local b WHERE (p.start_local>=b.start_local AND p.start_local<b.end_local)
            OR (p.end_local>=b.start_local AND p.end_local<b.end_local)) AS dst_excluded,
        cast(epoch(timezone('America/Chicago',p.start_local)) AS BIGINT) AS start_epoch,
        cast(epoch(timezone('America/Chicago',p.end_local)) AS BIGINT) AS end_epoch FROM parsed p'''


def prepare_csvs(root,manifest):
    records=[];out=root/'processed/trip_csv';out.mkdir(parents=True,exist_ok=True)
    for entry in manifest['files']:
        if entry.get('kind')!='trips' or entry.get('error'):continue
        zip_path=root/entry['path']
        with zipfile.ZipFile(zip_path) as archive:
            members=[x for x in archive.infolist() if x.filename.endswith('.csv') and not x.filename.startswith('__MACOSX/')]
            for i,member in enumerate(members):
                target=out/f"{entry['month']}-{i}.csv"
                if not target.exists() or target.stat().st_size!=member.file_size:
                    tmp=target.with_suffix('.csv.tmp')
                    with archive.open(member) as source,tmp.open('wb') as output:
                        shutil.copyfileobj(source,output,length=1024*1024)
                    if tmp.stat().st_size!=member.file_size:raise ValueError('Truncated CSV')
                    tmp.replace(target)
                records.append(dict(month=entry['month'],csv_path=str(target),source_zip_sha256=entry['sha256']))
        print(f"Prepared trip CSV {entry['month']}",flush=True)
    return records


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--reports',type=Path,default=Path('reports/divvy_data_audit'))
    p.add_argument('--manifests',type=Path,default=Path('data/manifests/divvy'))
    p.add_argument('--prepare-only',action='store_true')
    args=p.parse_args();root=args.data_root.resolve();out=args.reports;maps=args.manifests
    manifest=json.loads((root/'download_manifest.json').read_text())
    inputs=prepare_csvs(root,manifest)
    if args.prepare_only:return
    audit=json.loads((out/'audit_summary.json').read_text())
    out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute("SET memory_limit='2GB'");con.execute('SET threads=4');con.execute("SET TimeZone='UTC'")
    con.execute('SET temp_directory=?',[str(root/'processed/audit_tmp')])
    con.execute('CREATE TEMP TABLE bad_local(start_local TIMESTAMP,end_local TIMESTAMP,kind VARCHAR)')
    lower=datetime.fromisoformat(audit['first_observation_utc'].replace('Z','+00:00'))
    upper=datetime.fromisoformat(audit['last_observation_utc'].replace('Z','+00:00'))
    bad=dst_intervals(datetime(lower.year,1,1),datetime(upper.year+1,1,1))
    con.executemany('INSERT INTO bad_local VALUES (?,?,?)',bad)
    write_csv(out/'dst_exclusions.csv',[dict(local_start=str(a),local_end_exclusive=str(b),reason=c,timezone='America/Chicago') for a,b,c in bad])
    con.execute('CREATE TEMP TABLE splits(split VARCHAR,start_epoch BIGINT,end_epoch BIGINT)')
    con.executemany('INSERT INTO splits VALUES (?,?,?)',[(s['split'],int(datetime.fromisoformat(s['start_utc'].replace('Z','+00:00')).timestamp()),
        int(datetime.fromisoformat(s['end_utc_exclusive'].replace('Z','+00:00')).timestamp())) for s in audit['splits']])
    con.execute('CREATE TEMP TABLE historical AS SELECT *, cast(epoch(try_cast(first_observed_utc AS TIMESTAMPTZ)) AS BIGINT) AS lo, '
        'cast(epoch(try_cast(interval_end_utc_exclusive AS TIMESTAMPTZ)) AS BIGINT) AS hi FROM read_csv(?,header=true,all_varchar=true)',
        [str(maps/'station_id_map.csv')])
    con.execute('CREATE TEMP TABLE candidates AS SELECT station_id FROM read_csv(?,header=true,all_varchar=true)',[str(maps/'candidate_stations.csv')])
    con.execute('CREATE TEMP TABLE endpoint_mapping(month VARCHAR,trip_station_id VARCHAR,archive_station_id VARCHAR,endpoint_count BIGINT,min_epoch BIGINT,max_epoch BIGINT,max_distance_m DOUBLE,current_short_name_agreements BIGINT)')
    trip_rows=[]; training_parts=[]
    supported_columns={'ride_id','rideable_type','started_at','ended_at','start_station_id','end_station_id','start_station_name','end_station_name','start_lat','start_lng','end_lat','end_lng'}
    for entry in inputs:
        month=entry['month']
        con.execute('CREATE OR REPLACE TEMP TABLE raw AS SELECT * FROM read_csv(?,header=true,all_varchar=true)',[entry['csv_path']])
        columns={r[0] for r in con.execute('DESCRIBE raw').fetchall()}
        if not supported_columns<=columns:raise ValueError(f'Unexpected {month} schema: {supported_columns-columns}')
        con.execute('''CREATE OR REPLACE TEMP TABLE parsed AS SELECT row_number() OVER () AS trip_row_id,*,
            try_cast(started_at AS TIMESTAMP) AS start_local,try_cast(ended_at AS TIMESTAMP) AS end_local,
            try_cast(start_lat AS DOUBLE) AS s_lat,try_cast(start_lng AS DOUBLE) AS s_lon,
            try_cast(end_lat AS DOUBLE) AS e_lat,try_cast(end_lng AS DOUBLE) AS e_lon FROM raw''')
        con.execute(annotate_local_times_sql())
        # Values from ambiguous/nonexistent local times are computed by the SQL
        # engine but are NEVER admitted to mapping, overlap, or ride-time tables.
        raw_count,invalid_dates,dst_count,min_local,max_local=con.execute('SELECT count(*),count(*) FILTER(WHERE start_local IS NULL OR end_local IS NULL),count(*) FILTER(WHERE dst_excluded),min(start_local),max(start_local) FROM times').fetchall()[0]
        con.execute('''CREATE OR REPLACE TEMP TABLE valid AS SELECT *,end_epoch-start_epoch AS duration_seconds
            FROM times WHERE NOT dst_excluded AND start_local IS NOT NULL AND end_local IS NOT NULL''')
        overlap,bad_duration,missing_start,missing_end=con.execute('''SELECT
            count(*) FILTER(WHERE start_epoch>=? AND start_epoch<=?),
            count(*) FILTER(WHERE duration_seconds<60 OR duration_seconds>21600),
            count(*) FILTER(WHERE coalesce(trim(start_station_id),'')=''),
            count(*) FILTER(WHERE coalesce(trim(end_station_id),'')='') FROM valid''',[int(lower.timestamp()),int(upper.timestamp())]).fetchall()[0]
        con.execute('''CREATE OR REPLACE TEMP TABLE endpoints AS
            SELECT trip_row_id,'start' AS side,start_station_id AS trip_station_id,start_station_name AS name,
              regexp_replace(lower(trim(start_station_name)),'\\s+',' ','g') AS name_norm,
              start_epoch AS ts,s_lat AS lat,s_lon AS lon FROM valid
            UNION ALL SELECT trip_row_id,'end',end_station_id,end_station_name,
              regexp_replace(lower(trim(end_station_name)),'\\s+',' ','g'),end_epoch,e_lat,e_lon FROM valid''')
        con.execute('''CREATE OR REPLACE TEMP TABLE possible AS SELECT e.*,h.station_id,
            h.current_trip_short_name,
            sqrt(pow((e.lat-try_cast(h.lat AS DOUBLE))*111320,2)+
                 pow((e.lon-try_cast(h.lon AS DOUBLE))*111320*cos(radians(e.lat)),2)) AS distance_m
            FROM endpoints e JOIN historical h ON e.name_norm=h.name_norm AND e.ts>=h.lo AND e.ts<h.hi
            WHERE coalesce(trim(e.trip_station_id),'')<>'' AND e.lat IS NOT NULL AND e.lon IS NOT NULL''')
        con.execute('''CREATE OR REPLACE TEMP TABLE matched AS SELECT trip_row_id,side,
            min(trip_station_id) AS trip_station_id,min(station_id) AS station_id,
            min(ts) AS ts,min(distance_m) AS distance_m,
            bool_or(trip_station_id=current_trip_short_name) AS agrees_live_code
            FROM possible WHERE distance_m<=50 GROUP BY trip_row_id,side HAVING count(DISTINCT station_id)=1''')
        mapped_start,mapped_end=con.execute("SELECT count(*) FILTER(WHERE side='start'),count(*) FILTER(WHERE side='end') FROM matched").fetchall()[0]
        con.execute('INSERT INTO endpoint_mapping SELECT ?,trip_station_id,station_id,count(*),min(ts),max(ts),max(distance_m),count(*) FILTER(WHERE agrees_live_code) FROM matched GROUP BY trip_station_id,station_id',[month])
        con.execute('''CREATE OR REPLACE TEMP TABLE mapped_rides AS SELECT v.*,s.station_id AS start_archive_id,e.station_id AS end_archive_id
            FROM valid v JOIN matched s ON v.trip_row_id=s.trip_row_id AND s.side='start'
            JOIN matched e ON v.trip_row_id=e.trip_row_id AND e.side='end' ''')
        mapped_both=con.execute('SELECT count(*) FROM mapped_rides').fetchall()[0][0]
        eligible_overlap=con.execute('SELECT count(*) FROM mapped_rides WHERE start_epoch>=? AND start_epoch<=? AND duration_seconds BETWEEN 60 AND 21600',[int(lower.timestamp()),int(upper.timestamp())]).fetchall()[0][0]
        train_path=root/'processed/od_training_rides'/f'{month}-{Path(entry["csv_path"]).stem}.parquet'
        train_path.parent.mkdir(parents=True,exist_ok=True)
        con.execute('''COPY (SELECT r.start_archive_id,r.end_archive_id,r.duration_seconds,r.start_epoch
            FROM mapped_rides r JOIN splits s ON r.start_epoch>=s.start_epoch AND r.start_epoch<s.end_epoch
            WHERE s.split='train' AND r.end_epoch<s.end_epoch AND r.duration_seconds BETWEEN 60 AND 21600)
            TO ? (FORMAT PARQUET,COMPRESSION ZSTD)''',[str(train_path)])
        training_parts.append(str(train_path))
        stats=dict(month=month,raw_trip_rows=raw_count,invalid_timestamp_rows=invalid_dates,dst_ambiguous_or_nonexistent_rows=dst_count,
            min_started_at_local=str(min_local),max_started_at_local=str(max_local),
            exact_utc_start_overlap_rows=overlap,rows_outside_60s_to_6h_duration_filter=bad_duration,
            missing_start_station_id=missing_start,missing_end_station_id=missing_end,
            start_endpoints_mapped=mapped_start,end_endpoints_mapped=mapped_end,both_endpoints_mapped=mapped_both,
            mapped_and_duration_filtered_overlap=eligible_overlap,
            mapping_method='unique exact normalized historical name + <=50m endpoint coordinates + observed metadata interval',
            source_zip_sha256=entry['source_zip_sha256'])
        trip_rows.append(stats)
        write_csv(out/'trip_overlap_by_month.csv',trip_rows)
        print(f"Trips {month}: {raw_count:,}, mapped both={mapped_both:,}, DST excluded={dst_count:,}",flush=True)
    pattern=str(root/'processed/od_training_rides/*.parquet').replace('\\','/')
    con.execute('''CREATE TEMP TABLE od AS SELECT start_archive_id,end_archive_id,count(*) AS training_trips,
        median(duration_seconds) AS median_seconds,quantile_cont(duration_seconds,.9) AS p90_seconds
        FROM read_parquet(?) GROUP BY start_archive_id,end_archive_id''',[pattern])
    all_od=root/'processed/od_ride_times.parquet'
    con.execute('COPY od TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(all_od)])
    con.execute('''COPY (SELECT o.* FROM od o JOIN candidates s ON o.start_archive_id=s.station_id
        JOIN candidates e ON o.end_archive_id=e.station_id ORDER BY o.start_archive_id,o.end_archive_id)
        TO ? (FORMAT CSV,HEADER true)''',[str(out/'candidate_od_ride_times.csv')])
    con.execute('''COPY endpoint_mapping TO ? (FORMAT PARQUET,COMPRESSION ZSTD)''',[str(root/'processed/trip_station_mapping.parquet')])
    con.execute('''COPY (SELECT m.*, 'provisional_exact_name_geo_time_match' AS status FROM endpoint_mapping m
        JOIN candidates c ON m.archive_station_id=c.station_id ORDER BY month,trip_station_id)
        TO ? (FORMAT CSV,HEADER true)''',[str(maps/'trip_station_id_map.csv')])
    n_od,n_supported,n_trips=con.execute('SELECT count(*),count(*) FILTER(WHERE training_trips>=20),coalesce(sum(training_trips),0) FROM od').fetchall()[0]
    candidate_od,candidate_supported=con.execute('''SELECT count(*),count(*) FILTER(WHERE o.training_trips>=20)
        FROM od o JOIN candidates s ON o.start_archive_id=s.station_id JOIN candidates e ON o.end_archive_id=e.station_id''').fetchall()[0]
    totals={key:sum(r[key] for r in trip_rows) for key in ['raw_trip_rows','invalid_timestamp_rows','dst_ambiguous_or_nonexistent_rows',
        'exact_utc_start_overlap_rows','missing_start_station_id','missing_end_station_id','both_endpoints_mapped','mapped_and_duration_filtered_overlap']}
    result=dict(timezone='America/Chicago',timezone_database_version=importlib.metadata.version('tzdata'),
        timezone_basis='Explicit policy: naive trip timestamps interpreted as Chicago local time, based on service area and official GBFS timezone; CSV schema itself has no timezone annotation',
        dst_policy='exclude ambiguous/nonexistent start OR end local times; no guessed fold',
        monthly_files=len(inputs),**totals,
        mapped_both_rate=totals['both_endpoints_mapped']/totals['raw_trip_rows'],
        od_training_trip_rows=n_trips,od_pairs=n_od,od_pairs_with_20plus_training_trips=n_supported,
        candidate_od_pairs=candidate_od,candidate_od_pairs_20plus=candidate_supported,
        ride_time_filter='60 <= UTC duration_seconds <= 21600; both endpoints mapped; start and end in training split',
        matching_rule='exact normalized name + unique historical publisher UID within observed metadata interval + <=50m coordinates; no fuzzy-name guesses',
        scope_limit='Trip/metadata overlap does NOT prove arrival inventory observable or make every trip replayable',
        interpretation='Completed rides only; does not represent unserved demand',
        stored_locally=['processed/trip_csv','processed/od_training_rides','processed/od_ride_times.parquet','processed/trip_station_mapping.parquet'],
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'trip_overlap.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'trip_overlap.md').write_text(f'''# Official Divvy trips: overlap and OD audit

Read **{totals['raw_trip_rows']:,}** actual trip rows in **{len(inputs)}** monthly CSV inputs, not just filenames.
Raw ZIP/CSV and full joined/OD tables stay outside the repository.

- Valid, unambiguous UTC starts within the historical event range: **{totals['exact_utc_start_overlap_rows']:,}**.
- DST ambiguous/nonexistent start or end timestamps excluded: **{totals['dst_ambiguous_or_nonexistent_rows']:,}**; policy uses IANA America/Chicago, never Pacific or a fixed offset. See `dst_exclusions.csv`.
- Both endpoints conservatively mapped to historical archive identities: **{totals['both_endpoints_mapped']:,}** ({100*result['mapped_both_rate']:.2f}% of all raw trips).
- Mapped, duration-filtered trips in the exact UTC overlap: **{totals['mapped_and_duration_filtered_overlap']:,}**.
- Training-only eligible trips for ride-time estimates: **{n_trips:,}**; OD pairs: **{n_od:,}**; pairs with >=20 training trips: **{n_supported:,}**.
- Among the provisional training-area candidates: **{candidate_od}** observed OD pairs; **{candidate_supported}** have >=20 training trips. Others must use the proposal's documented geometric fallback.

Mapping requires an exact whitespace/case-normalized name, <=50m endpoint coordinates, a compatible observed historical metadata interval, and a unique publisher station identity. It does not assume trip codes equal GBFS UUIDs or use today's metadata as historical truth.
The CSV's timestamps have no timezone annotation. Chicago localization is an explicit policy based on the service area and official GBFS timezone, not a claim that the CSV schema independently certifies that convention.
The candidate-only mapping and OD aggregates are available in the repository; full tables stay in external local storage. Mapping remains provisional pending final station/rule approval.

OD medians use only training trips, with both start/end inside training and UTC ride duration from 60 seconds to 6 hours. Tuning, calibration, and test rides do not estimate ride times.
These overlap counts do **not** mean all trips have observable pickup/return inventory: the change-event archive's heartbeat and arrival-label limitations still apply. Completed-trip sampling also misses unmet demand.

See `trip_overlap_by_month.csv`, `trip_overlap.json`, and `licensing_and_overlap.md` for details and source restrictions.
''',encoding='utf-8')
    con.close();print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
