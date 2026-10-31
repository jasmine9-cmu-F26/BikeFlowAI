"""Offline synthetic regression checks for official snapshots and the collector."""
from datetime import datetime,timezone
import csv
import gzip
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
sys.path.insert(0,str(ROOT/'scripts/data'))
from audit_chicago_historical import normalize,grid_coverage,current_match
from audit_chicago_trips import endpoint_match,observable,utc_epoch


class ChicagoSnapshotTests(unittest.TestCase):
    def test_full_snapshots_keep_unchanged_counts_and_exact_long_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sid='900719925474099312345678901'
            rows=[]
            for ts,status in [('2021-05-03T00:05:15','In Service'),('2021-05-03T00:15:15','Not In Service')]:
                rows.append(dict(id=sid,timestamp=ts,station_name='Synthetic station',total_docks='10',docks_in_service='10',available_bikes='2',available_docks='8',status=status,latitude='41.88',longitude='-87.64',record=sid+ts))
            p=root/'sample.json.gz';p.write_bytes(gzip.compress(json.dumps(rows).encode()))
            manifest=dict(settings=dict(start_local='2021-05-03T00:00:00',end_local_exclusive='2021-08-30T00:00:00'),files=[dict(kind='snapshots',path=p.name,saved_sha256=hashlib.sha256(p.read_bytes()).hexdigest())])
            con=duckdb.connect();con.execute("SET TimeZone='UTC'")
            n,invalid,conflicts,out=normalize(con,root,manifest)
            result=con.execute('SELECT station_id,timestamp,num_bikes_available,is_in_service FROM snapshots ORDER BY timestamp').fetchall()
            self.assertEqual((n,invalid,conflicts),(2,0,0))
            self.assertEqual([r[0] for r in result],['chicago:'+sid]*2)
            self.assertEqual([r[2] for r in result],[2,2])
            self.assertEqual([r[3] for r in result],[True,False])
            self.assertEqual(result[0][1],int(datetime(2021,5,3,5,5,15,tzinfo=timezone.utc).timestamp()))
            con.close()

    def test_grid_denominator_does_not_shrink_to_station_lifetime(self):
        hits,expected,ratio=grid_coverage(np.array([360,361]),0,3600,phase=360)
        self.assertEqual((hits,expected,ratio),(1,6,1/6))

    def test_live_names_geometry_and_ambiguity(self):
        record=dict(station_id='12345678901234567890',name='Synthetic A',lat=41.88,lon=-87.64)
        state,match,distance=current_match(' synthetic a ',41.88,-87.64,[record])
        self.assertEqual(state,'exact_name_geo_unique');self.assertEqual(match['station_id'],'12345678901234567890')
        other=dict(record,station_id='different')
        self.assertEqual(current_match('Synthetic A',41.88,-87.64,[record,other])[0],'ambiguous')

    def test_trip_mapping_and_observation_gaps(self):
        mapping={'synthetic a':[dict(station_id='chicago:1',lo=0,hi=2000,lat=41.88,lon=-87.64)]}
        self.assertEqual(endpoint_match('Synthetic A',41.88,-87.64,100,mapping)[0],'chicago:1')
        self.assertIsNone(endpoint_match('Synthetic A',40.88,-87.64,100,mapping)[0])
        self.assertIsNone(endpoint_match('Synthetic A',41.88,-87.64,3000,mapping)[0])
        self.assertFalse(observable(1000,[0,2000],300));self.assertTrue(observable(1700,[0,2000],300))
        status,epoch=utc_epoch(datetime(2021,5,3,0,5,15),{})
        self.assertEqual(status,'unique');self.assertEqual(epoch,int(datetime(2021,5,3,5,5,15,tzinfo=timezone.utc).timestamp()))

    def test_streamed_trip_OD_excludes_held_out_and_far_coordinate_rides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'external';out=root/'reports';maps=root/'maps'
            data.mkdir();out.mkdir();maps.mkdir();(data/'processed').mkdir()
            def epoch(value):return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp())
            lo='2021-05-03T05:00:00Z';hi='2021-08-30T05:00:00Z';train_end='2021-07-12T05:00:00Z'
            (out/'audit_summary.json').write_text(json.dumps(dict(sample_start_utc=lo,sample_end_utc_exclusive=hi,
                splits=[dict(start_utc=lo,end_utc_exclusive=train_end)])))
            with (maps/'selected_stations.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['station_id']);w.writerows([['chicago:A'],['chicago:B']])
            with (maps/'station_id_map.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['station_id','name_norm','lat','lon','first_observed_utc','interval_end_utc_exclusive'])
                w.writerows([['chicago:A','synthetic a',41.88,-87.64,lo,hi],['chicago:B','synthetic b',41.89,-87.65,lo,hi]])
            frames=[dict(station_id=sid,timestamp=epoch(t),num_bikes_available=2,num_docks_available=8,is_in_service=True)
                for sid in ['chicago:A','chicago:B'] for t in ['2021-05-04T17:00:00Z','2021-05-04T17:10:00Z','2021-08-10T17:00:00Z','2021-08-10T17:30:00Z']]
            pq.write_table(pa.Table.from_pylist(frames),data/'processed/snapshots.parquet')
            header=['started_at','ended_at','start_station_id','end_station_id','start_station_name','end_station_name','start_lat','start_lng','end_lat','end_lng']
            stream=io.StringIO();writer=csv.writer(stream);writer.writerow(header)
            writer.writerows([
                ['2021-05-04 12:00:00','2021-05-04 12:10:00','trip-A','trip-B','Synthetic A','Synthetic B',41.88,-87.64,41.89,-87.65],
                ['2021-08-10 12:00:00','2021-08-10 12:30:00','trip-A','trip-B','Synthetic A','Synthetic B',41.88,-87.64,41.89,-87.65],
                ['2021-05-05 12:00:00','2021-05-05 12:10:00','trip-A','trip-B','Synthetic A','Synthetic B',40.88,-87.64,41.89,-87.65]])
            with zipfile.ZipFile(data/'synthetic.zip','w') as z:z.writestr('synthetic.csv',stream.getvalue())
            (data/'download_manifest.json').write_text(json.dumps(dict(files=[dict(kind='trips',month='202105',path='synthetic.zip',sha256=hashlib.sha256((data/'synthetic.zip').read_bytes()).hexdigest())])))
            result=subprocess.run([sys.executable,str(ROOT/'scripts/data/audit_chicago_trips.py'),'--data-root',str(data),'--reports',str(out),'--manifests',str(maps)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            audit=json.loads((out/'trip_overlap.json').read_text())
            self.assertEqual(audit['raw_rows'],3);self.assertEqual(audit['both_endpoints_mapped_in_sample'],2)
            self.assertEqual(audit['eligible_training_OD_rides'],1)
            with (out/'od_ride_times.csv').open() as f:od=list(csv.DictReader(f))
            self.assertEqual(float(od[0]['median_seconds']),600)




if __name__=='__main__':unittest.main()
