"""Synthetic causal feature, B2, interval and injected-leakage regressions."""
from pathlib import Path
import sys,tempfile,unittest,math
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/data'))
from build_audited_features import build_station_features,fit_b2,audit_tables
from pipeline_audit_common import asof_indices,iso
from audit_final_trip_od import write_weekly_od


def source():
    t=np.arange(0,31200,600,dtype=np.int64);n=len(t)
    return dict(timestamp=t,num_bikes_available=np.full(n,2),num_docks_available=np.full(n,8),
        is_in_service=np.ones(n,dtype=bool),lat=np.full(n,41.88),lon=np.full(n,-87.64),capacity=np.full(n,10),docks_in_service=np.full(n,10))


class FinalPipelineTests(unittest.TestCase):
    def test_freshness_thresholds_are_backward_and_inclusive(self):
        self.assertEqual(asof_indices([0,1200],[599,600,601,899,900,901,1199,1200],600).tolist(),[0,0,-1,-1,-1,-1,-1,1])
        self.assertEqual(asof_indices([0,1200],[900,901],900).tolist(),[0,-1])

    def test_future_values_do_not_change_current_features(self):
        a=source();scope=dict(name='train',lo=0,hi=7200)
        f,l,_=build_station_features('chicago:synthetic',a,scope,[10],{})
        first=f[0].slice(0,1)
        a['num_bikes_available'][a['timestamp']>360]=0;a['capacity'][a['timestamp']>360]=99
        other,targets,_=build_station_features('chicago:synthetic',a,scope,[10],{})
        left=first.to_pylist()[0];right=other[0].to_pylist()[0]
        for key,value in left.items():
            if isinstance(value,float) and math.isnan(value):self.assertTrue(math.isnan(right[key]))
            else:self.assertEqual(value,right[key],key)
        self.assertNotEqual(l[0]['bike_unavailable'][0].as_py(),targets[0]['bike_unavailable'][0].as_py())

    def test_lags_remain_missing_at_cold_start_and_targets_stay_in_split(self):
        f,l,_=build_station_features('chicago:synthetic',source(),dict(name='train',lo=0,hi=7200),[10,60],{})
        for table in f:
            r=table.to_pylist()[0];self.assertTrue(r['lag_60m_missing']);self.assertIsNone(r['lag_60m_snapshot_time'])
            for r in table.to_pylist():
                for m in [10,30,60]:
                    if r[f'lag_{m}m_snapshot_time'] is not None:self.assertLessEqual(r[f'lag_{m}m_snapshot_time'],r['request_time']-m*60)
        for table in l:
            for r in table.to_pylist():self.assertGreater(r['target_snapshot_time'],r['request_time']);self.assertLess(r['target_snapshot_time'],7200)

    def test_B2_uses_only_prior_training_observations(self):
        a=source();t=a['timestamp'];valid=np.ones(len(t),dtype=bool)
        first=fit_b2('s',t,a['num_bikes_available'],a['num_docks_available'],a['is_in_service'],valid,0,7200,{})
        a['num_bikes_available'][t>=7200]=0
        again=fit_b2('s',t,a['num_bikes_available'],a['num_docks_available'],a['is_in_service'],valid,0,7200,{})
        self.assertEqual(first,again)
        self.assertTrue(all(r['source_max_timestamp']<7200 for r in first))
        self.assertEqual(fit_b2('s',t,a['num_bikes_available'],a['num_docks_available'],a['is_in_service'],valid,0,0,{}),[])

    def test_training_replay_OD_excludes_later_week_and_cross_boundary_ride(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);out=target/'reports';out.mkdir()
            def ride(start,end,duration):return dict(start_station_id='a',end_station_id='b',request_time=start,return_time=end,duration_seconds=duration,train_OD_eligible=True)
            records=[ride(100,200,100) for _ in range(20)]+[ride(604801,604901,9000) for _ in range(20)]+[ride(604700,604900,200)]
            planner=[dict(start_station_id='a',end_station_id='b',straight_line_m='1000',self_pair='False')]
            fits=write_weekly_od(records,planner,dict(lo=0,hi=6048000),target,out)
            rows=pq.read_table(target/'OD/training_expanding_week_od.parquet').to_pylist()
            first=next(r for r in rows if r['version']=='train_week_0');second=next(r for r in rows if r['version']=='train_week_1')
            self.assertEqual(first['method'],'geometric_fallback_runtime_coordinates');self.assertIsNone(first['ride_seconds']);self.assertIsNone(first['straight_line_m'])
            self.assertEqual(second['training_trips'],20);self.assertEqual(second['ride_seconds'],100)
            self.assertEqual(fits[1]['source_max_trip_end_utc'],iso(200))

    def test_actual_table_auditor_rejects_injected_future_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'processed/final_pipeline_v1';(root/'features').mkdir(parents=True);(root/'labels').mkdir()
            scopes=[dict(name=n,lo=i*7200,hi=(i+1)*7200) for i,n in enumerate(['train','tune','calibration','test'])]
            allf=[];alll=[]
            for scope in scopes:
                f,l,_=build_station_features('s',source(),scope,[10],{});allf.extend(f);alll.extend(l)
            features=pa.concat_tables(allf);values=features['base_snapshot_time'].to_pylist();values[0]=features['request_time'][0].as_py()+1
            features=features.set_column(features.schema.get_field_index('base_snapshot_time'),'base_snapshot_time',pa.array(values))
            pq.write_table(features,root/'features/part.parquet');pq.write_table(pa.concat_tables(alll),root/'labels/part.parquet')
            out=Path(tmp)/'reports';out.mkdir()
            protocol=dict(chronological_splits=[dict(split=s['name'],start_utc=iso(s['lo']),end_utc_exclusive=iso(s['hi'])) for s in scopes])
            with self.assertRaisesRegex(ValueError,'leakage/invariant'):
                audit_tables(root,out,protocol,dict(training_max_trip_end_utc=iso(7000)),[])


if __name__=='__main__':unittest.main()
