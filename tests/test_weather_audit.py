"""Weather availability/missingness tests; no live API calls."""
from pathlib import Path
import sys
import unittest
import math
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/data'))
from audit_weather_data import summarize_hourly,candidate_indices,causal_run_index,VARIABLES


class WeatherAuditTests(unittest.TestCase):
    def document(self,times):
        return dict(hourly=dict(time=times,**{name:[1.]*len(times) for name in VARIABLES}),hourly_units={name:'synthetic' for name in VARIABLES})

    def test_missing_timestamp_stays_in_expected_denominator(self):
        result=summarize_hourly(self.document([0,7200]),0,10800)
        self.assertEqual(result[0]['expected_hours'],3)
        self.assertEqual(result[0]['missing_hours'],1)
        self.assertAlmostEqual(result[0]['missing_fraction'],1/3)

    def test_null_nan_inf_and_missing_variable_are_not_valid_values(self):
        document=self.document([0,3600,7200]);document['hourly']['temperature_2m']=[None,float('nan'),float('inf')]
        del document['hourly']['precipitation_probability']
        result={r['variable']:r for r in summarize_hourly(document,0,10800)}
        self.assertEqual(result['temperature_2m']['missing_hours'],3)
        self.assertEqual(result['precipitation_probability']['missing_fraction'],1)

    def test_duplicate_unordered_or_misaligned_arrays_are_rejected(self):
        for times in [[0,0],[3600,0],[30,3630]]:
            with self.assertRaises(ValueError):summarize_hourly(self.document(times),0,7200)
        doc=self.document([0,3600]);doc['hourly']['temperature_2m']=[1]
        with self.assertRaises(ValueError):summarize_hourly(doc,0,7200)

    def test_candidate_calendar_join_never_uses_future_or_stale_valid_time(self):
        result=candidate_indices([3600,7200],[3599,3600,7199,7200,10800,10801])
        self.assertEqual(result.tolist(),[-1,0,0,1,1,-1])
        self.assertEqual(candidate_indices([], [0]).tolist(),[-1])

    def test_issuance_gate_rejects_hourly_timestamp_only_and_late_release(self):
        runs=[dict(valid_time=1000),dict(valid_time=1000,issued_at=0,available_at=901),
              dict(valid_time=1000,issued_at=0,available_at=800),dict(valid_time=1000,issued_at=901,available_at=850)]
        self.assertEqual(causal_run_index(runs,900,1000),2)
        self.assertEqual(causal_run_index(runs[:2],900,1000),-1)
        self.assertEqual(causal_run_index(runs,900,2000),-1)

    def test_asof_selects_latest_available_run_not_latest_retrospective_run(self):
        runs=[dict(valid_time=2000,issued_at=100,available_at=200),dict(valid_time=2000,issued_at=300,available_at=400),dict(valid_time=2000,issued_at=500,available_at=600)]
        self.assertEqual(causal_run_index(runs,450,2000),1)


if __name__=='__main__':unittest.main()
