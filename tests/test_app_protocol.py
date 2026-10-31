"""Causal feature timing and fixed app-cohort identity checks."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/data'))
from bikeflow_data.temporal import asof_index,nearest_valid_matches,classify_local
from build_app_cohort import select_app_stations
from datetime import datetime


class AppProtocolTests(unittest.TestCase):
    def test_asof_never_reads_future_and_rejects_stale_context(self):
        times=[100,700,1300]
        self.assertEqual(asof_index(times,699),0)
        self.assertEqual(asof_index(times,700),1)
        self.assertEqual(asof_index(times,99),-1)
        self.assertEqual(asof_index(times,2200),2)
        self.assertEqual(asof_index(times,2201),-1)
        self.assertEqual(asof_index([],700),-1)
        with self.assertRaises(ValueError):asof_index(times,700,-1)

    def test_future_label_matching_is_separate_from_causal_features(self):
        times=np.array([100,700,1300]);valid=np.ones(3,dtype=bool)
        self.assertEqual(asof_index(times,699),0)
        ix,err=nearest_valid_matches(times,valid,np.array([1299]),0,2000,after_times=np.array([699]))
        self.assertEqual(ix.tolist(),[2]);self.assertEqual(err.tolist(),[1])
        ix,_=nearest_valid_matches(times,valid,np.array([1299]),0,1300,after_times=np.array([699]))
        self.assertEqual(ix.tolist(),[1])

    def test_shared_timezone_rejects_chicago_dst_fold_and_gap(self):
        self.assertEqual(classify_local(datetime(2021,11,7,1,30))[0],'ambiguous')
        self.assertEqual(classify_local(datetime(2021,3,14,2,30))[0],'nonexistent')

    def test_app_selection_requires_training_qualification_and_unique_live_id(self):
        selected=[dict(station_id='chicago:A',historical_station_id='A',name='Synthetic A',train_lat='41.8',train_lon='-87.6')]
        row=dict(station_id='chicago:A',match_status='exact_name_geo_unique',historical_name='Synthetic A',
            current_station_id='9007199254740993123456789',current_name='Synthetic A',current_short_name='A',distance_m='1')
        app=select_app_stations(selected,[row,dict(row,station_id='not-training-qualified')])
        self.assertEqual(len(app),1)
        self.assertEqual(app[0]['current_station_id'],'9007199254740993123456789')
        with self.assertRaises(ValueError):select_app_stations(selected,[row,row])
        with self.assertRaises(ValueError):select_app_stations(selected,[dict(row,current_name='Different')])


if __name__=='__main__':unittest.main()
