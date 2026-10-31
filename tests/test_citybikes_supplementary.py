"""Offline synthetic checks for the Divvy source migration."""
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'legacy/citybikes/scripts/data'))
from audit_divvy_data import nearest_valid_matches,observed_grid_coverage
from audit_divvy_trips import classify_local,annotate_local_times_sql
from extract_citybikes_divvy import normalize_sql


class DivvyTemporalTests(unittest.TestCase):
    def test_nearest_search_skips_invalid_observation(self):
        indices,errors=nearest_valid_matches(np.array([0,400,500]),np.array([True,False,True]),np.array([420]),0,1000)
        self.assertEqual(indices.tolist(),[2]);self.assertEqual(errors.tolist(),[80])

    def test_nearest_valid_tie_and_split_boundary(self):
        t=np.array([0,420,900]);valid=np.ones(3,dtype=bool)
        ix,err=nearest_valid_matches(t,valid,np.array([210,840]),0,840)
        self.assertEqual(ix.tolist(),[0,1]);self.assertEqual(err.tolist(),[210,420])
        ix,err=nearest_valid_matches(t,np.zeros(3,dtype=bool),np.array([210]),0,840)
        self.assertEqual(ix.tolist(),[-1]);self.assertTrue(np.isinf(err[0]))

    def test_silence_is_not_forward_filled(self):
        observed,expected,ratio=observed_grid_coverage(np.array([420,425]),0,1680,420,210)
        self.assertEqual((observed,expected,ratio),(1,4,.25))

    def test_wide_tolerance_cannot_reuse_request_as_future_label(self):
        ix,error=nearest_valid_matches(np.array([0,850]),np.ones(2,dtype=bool),np.array([420]),0,1000,after_times=np.array([0]))
        # The request itself is closer, but only the future observation may label it.
        self.assertEqual(ix.tolist(),[1]);self.assertEqual(error.tolist(),[430])
        ix,error=nearest_valid_matches(np.array([0]),np.ones(1,dtype=bool),np.array([420]),0,1000,after_times=np.array([0]))
        self.assertEqual(ix.tolist(),[-1]);self.assertTrue(np.isinf(error[0]))

    def test_chicago_dst_and_ordinary_time(self):
        self.assertEqual(classify_local(datetime(2024,11,3,1,30))[0],'ambiguous')
        self.assertEqual(classify_local(datetime(2025,3,9,2,30))[0],'nonexistent')
        status,utc=classify_local(datetime(2025,6,1,12))
        self.assertEqual(status,'unique');self.assertEqual(utc,datetime(2025,6,1,17,tzinfo=timezone.utc))

    def test_sql_dst_filter_only_excludes_affected_rides(self):
        con=duckdb.connect();con.execute("SET TimeZone='UTC'")
        con.execute('CREATE TEMP TABLE bad_local(start_local TIMESTAMP,end_local TIMESTAMP,kind VARCHAR)')
        con.execute("INSERT INTO bad_local VALUES ('2024-11-03 01:00','2024-11-03 02:00','ambiguous')")
        con.execute('CREATE TEMP TABLE parsed(trip_row_id INTEGER,start_local TIMESTAMP,end_local TIMESTAMP)')
        con.execute("INSERT INTO parsed VALUES (1,'2024-11-03 01:30','2024-11-03 02:10'),(2,'2024-12-03 01:30','2024-12-03 02:10'),(3,'2024-11-03 00:50','2024-11-03 01:10')")
        con.execute(annotate_local_times_sql())
        self.assertEqual(con.execute('SELECT trip_row_id,dst_excluded FROM times ORDER BY trip_row_id').fetchall(),[(1,True),(2,False),(3,True)])
        con.close()


class DivvyPipelineTests(unittest.TestCase):
    def test_normalizer_preserves_counts_uid_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.parquet'
            row=dict(tag='divvy',id='synthetic-hash',nuid='synthetic-publisher-uid',name='Synthetic A',
                latitude=41.88,longitude=-87.64,bikes=3,free=10,
                extra=json.dumps(dict(slots=15,renting=1,returning=0,last_updated=1735689590,ebikes=2)),
                timestamp=datetime(2025,1,1))
            pq.write_table(pa.Table.from_pylist([row]),path)
            c=duckdb.connect();r=c.sql(normalize_sql(),params=['202501',path.name,'synthetic-sha',str(path)]).to_arrow_table().to_pylist()[0]
            self.assertEqual(r['station_id'],'synthetic-publisher-uid')
            self.assertEqual(r['num_bikes_available'],3) # e-bikes already included
            self.assertEqual(r['num_docks_available'],10)
            self.assertIsNone(r['is_installed']);self.assertIsNone(r['num_bikes_disabled'])
            self.assertIsNone(r['is_virtual']);self.assertFalse(r['is_returning'])
            c.close()

    def test_synthetic_extraction_audit_trip_mapping_and_training_od(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'external';data.mkdir();reports=Path(tmp)/'reports';maps=Path(tmp)/'manifests'
            rows=[]
            stations=[('synthetic-A','Synthetic A',41.88,-87.64),('synthetic-B','Synthetic B',41.89,-87.65)]
            for ts in [datetime(2025,1,1,12),datetime(2025,8,1,12)]:
                epoch=int(ts.replace(tzinfo=timezone.utc).timestamp())
                for sid,name,lat,lon in stations:
                    rows.append(dict(tag='divvy',id=sid+'-hash',nuid=sid,name=name,latitude=lat,longitude=lon,bikes=3,free=7,
                        extra=json.dumps(dict(slots=10,renting=1,returning=1,last_updated=epoch-30)),timestamp=ts))
            raw=data/'synthetic.parquet';pq.write_table(pa.Table.from_pylist(rows),raw)
            trip_zip=data/'synthetic.zip';stream=io.StringIO();fields=['ride_id','rideable_type','started_at','ended_at','start_station_id','end_station_id','start_station_name','end_station_name','start_lat','start_lng','end_lat','end_lng']
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            writer.writerow(dict(zip(fields,['synthetic-ride','classic_bike','2025-01-07 12:00:00','2025-01-07 12:10:00','trip-A','trip-B','Synthetic A','Synthetic B',41.88,-87.64,41.89,-87.65])))
            # A held-out ride is mapped but must not change the training OD median.
            writer.writerow(dict(zip(fields,['synthetic-test-ride','classic_bike','2025-07-07 12:00:00','2025-07-07 12:30:00','trip-A','trip-B','Synthetic A','Synthetic B',41.88,-87.64,41.89,-87.65])))
            # Exact names alone cannot map an endpoint with distant coordinates.
            writer.writerow(dict(zip(fields,['synthetic-far-ride','classic_bike','2025-01-08 12:00:00','2025-01-08 12:10:00','trip-A','trip-B','Synthetic A','Synthetic B',40.88,-87.64,41.89,-87.65])))
            with zipfile.ZipFile(trip_zip,'w') as z:z.writestr('synthetic.csv',stream.getvalue())
            files=[dict(kind='citybikes',month='202501',path=raw.name,sha256=hashlib.sha256(raw.read_bytes()).hexdigest()),
                   dict(kind='trips',month='202501',path=trip_zip.name,sha256=hashlib.sha256(trip_zip.read_bytes()).hexdigest())]
            manifest=dict(completed_at_utc='2026-10-30T00:00:00Z',files=files,total_raw_download_bytes=sum(p.stat().st_size for p in [raw,trip_zip]),
                live=[dict(name='station_status',captured_at_utc='2026-10-30T00:00:00Z')])
            (data/'download_manifest.json').write_text(json.dumps(manifest))
            live=data/'raw/live';live.mkdir(parents=True)
            (live/'station_information.json').write_text(json.dumps(dict(data=dict(stations=[dict(station_id=s[0],short_name='trip-'+s[0][-1]) for s in stations]))))
            (live/'station_status.json').write_text(json.dumps(dict(version='2.3',data=dict(stations=[dict(station_id=s[0],is_installed=1,is_renting=1,is_returning=1) for s in stations]))))
            (live/'system_information.json').write_text(json.dumps(dict(data=dict(timezone='America/Chicago'))))
            commands=[['extract_citybikes_divvy.py'],['audit_divvy_data.py','--reports',str(reports),'--manifests',str(maps)],
                ['audit_divvy_trips.py','--reports',str(reports),'--manifests',str(maps)]]
            for command in commands:
                run=subprocess.run([sys.executable,str(ROOT/'legacy/citybikes/scripts/data'/command[0]),'--data-root',str(data),*command[1:]],capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
            audit=json.loads((reports/'audit_summary.json').read_text())
            self.assertFalse(audit['training_ready']);self.assertEqual(audit['raw_event_rows'],4)
            trips=json.loads((reports/'trip_overlap.json').read_text())
            self.assertEqual(trips['raw_trip_rows'],3);self.assertEqual(trips['both_endpoints_mapped'],2)
            self.assertEqual(trips['od_training_trip_rows'],1)
            self.assertEqual(trips['candidate_od_pairs_20plus'],0)
            table=pq.read_table(data/'processed/od_ride_times.parquet').to_pylist()
            self.assertEqual(table[0]['median_seconds'],600)


if __name__=='__main__':unittest.main()
