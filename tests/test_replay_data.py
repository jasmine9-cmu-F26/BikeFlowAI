"""Assembling a Replay from a synthetic final_pipeline_v1 tree."""

from pathlib import Path
import csv, json, math, shutil, sys, tempfile, unittest
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts/rl"))
from replay_data import load_replay
from replay_env import BIKES, DOCKS, P_BIKE, B2_BIKE, B2_DOCK, HORIZONS

DAY, WEEK = 86400, 7 * 86400
T0 = 1620018000  # 2021-05-03 05:00 UTC, train start
GRID0 = T0 + 360
TUNE0 = T0 + 4 * WEEK + 3600 + 360
STATIONS = {
    "chicago:1": (41.88, -87.63),
    "chicago:2": (41.88, -87.6253),
    "chicago:3": (41.88, -87.57),
}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def build(root):
    project, data = root / "project", root / "data"
    write_csv(
        project / "data/manifests/chicago/app_stations.csv",
        [
            dict(station_id=s, historical_lat=lat, historical_lon=lon)
            for s, (lat, lon) in STATIONS.items()
        ],
    )
    contract = project / "data/manifests/chicago/final_pipeline_contract.json"
    contract.write_text(
        json.dumps(
            {
                "chronological_splits": [
                    {"split": "train", "start_utc": "2021-05-03T05:00:00Z"}
                ]
            }
        )
    )
    write_csv(
        project / "reports/final_pipeline_audit/trip_od/planner_od.csv",
        [
            dict(
                start_station_id=a,
                end_station_id=b,
                method="training_median"
                if (a, b) == ("chicago:1", "chicago:2")
                else "geometric_fallback",
                ride_seconds=500.0 if (a, b) == ("chicago:1", "chicago:2") else 1.0,
            )
            for a in STATIONS
            for b in STATIONS
        ],
    )
    table = data / "processed/final_pipeline_v1"
    for sub in ("features", "labels", "B2", "OD"):
        (table / sub).mkdir(parents=True)
    scores = {"train": [], "tune": []}
    for split, lo, hi in (
        ("train", GRID0, T0 + 4 * WEEK - 3600),
        ("tune", TUNE0, TUNE0 + 3 * DAY),
    ):
        for sid in ("chicago:1", "chicago:2"):
            q = np.arange(lo, hi, 600, dtype=np.int64)
            k = (q - (GRID0 if split == "train" else TUNE0)) // 600
            feats, labels = [], []
            for h in (10, 20):
                ids = [f"{sid}|{t}|{h}" for t in q]
                bikes = k % 7
                feats.append(
                    pa.table(
                        dict(
                            station_id=[sid] * len(q),
                            request_time=q,
                            horizon_minutes=np.full(len(q), h, np.int16),
                            num_bikes_available=bikes,
                            num_docks_available=10 - bikes,
                            capacity=np.full(len(q), 10),
                            is_in_service=np.ones(len(q), bool),
                            row_id=ids,
                            split=[split] * len(q),
                        )
                    )
                )
                labels.append(
                    pa.table(
                        dict(
                            row_id=ids,
                            bike_unavailable=(bikes == 0).astype(np.int8),
                            dock_unavailable=(k % 11 == 0).astype(np.int8),
                        )
                    )
                )
                week = (q - T0) // WEEK
                keep = week >= 2 if split == "train" else np.ones(len(q), bool)
                scores[split].append(
                    pa.table(
                        dict(
                            row_id=np.array(ids)[keep],
                            p_bike_unavailable=(0.01 * (k % 50))[keep],
                            p_dock_unavailable=np.full(int(keep.sum()), 0.5),
                        )
                    )
                )
            name = sid.replace(":", "_")
            pq.write_table(
                pa.concat_tables(feats), table / f"features/{name}_{split}.parquet"
            )
            pq.write_table(
                pa.concat_tables(labels), table / f"labels/{name}_{split}.parquet"
            )
    for split, parts in scores.items():
        path = data / f"scores_{split}.parquet"
        pq.write_table(pa.concat_tables(parts), path)
    cells = [(s, w, h) for s in STATIONS for w in range(7) for h in range(24)]
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    station_id=s,
                    weekday=w,
                    hour=h,
                    bike_available_rate=0.8,
                    dock_available_rate=0.9,
                    version="heldout_final",
                )
                for s, w, h in cells
            ]
        ),
        table / "B2/heldout_training_fit_rates.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    station_id=s,
                    weekday=w,
                    hour=h,
                    bike_available_rate=0.5 + 0.01 * v,
                    dock_available_rate=0.6,
                    version=f"train_week_{v}",
                )
                for v in range(1, 4)
                for s, w, h in cells
            ]
        ),
        table / "B2/training_expanding_week_rates.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    start_station_id=a,
                    end_station_id=b,
                    version=f"train_week_{v}",
                    ride_seconds=400.0 + v
                    if (a, b) == ("chicago:1", "chicago:2") and v
                    else None,
                )
                for v in range(4)
                for a in STATIONS
                for b in STATIONS
            ]
        ),
        table / "OD/training_expanding_week_od.parquet",
    )
    req = [
        (
            "chicago:1",
            "chicago:2",
            T0 + 3 * DAY,
            "train",
            True,
        ),  # week 0: no scores, dropped
        ("chicago:1", "chicago:2", T0 + 2 * WEEK + DAY, "train", True),
        ("chicago:2", "chicago:1", T0 + 3 * WEEK + DAY, "train", False),  # not retained
        ("chicago:2", "chicago:1", TUNE0 + DAY, "tune", True),
        ("chicago:2", "chicago:99", TUNE0 + DAY, "tune", True),  # outside app stations
        ("chicago:1", "chicago:2", T0 + 4 * WEEK + 60, "purge", True),
    ]
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    start_station_id=a,
                    end_station_id=b,
                    request_time=t,
                    split=s,
                    replay_15min_request_retained=r,
                )
                for a, b, t, s, r in req
            ]
        ),
        table / "mapped_app32_requests.parquet",
    )
    return project, data


class LoadReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project, self.data = build(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, split):
        return load_replay(
            self.data, self.project, split, self.data / f"scores_{split}.parquet"
        )

    def test_decision_and_outcome_rows_land_on_their_grid_cell(self):
        r = self.load("tune")
        self.assertEqual(r.grid0, TUNE0)
        s, k, h = r.stations.index("chicago:2"), 13, HORIZONS.index(20)
        self.assertEqual(r.decision[s, k, h, BIKES], 13 % 7)
        self.assertEqual(r.decision[s, k, h, DOCKS], 10 - 13 % 7)
        self.assertAlmostEqual(float(r.decision[s, k, h, P_BIKE]), 0.13, places=6)
        self.assertAlmostEqual(float(r.decision[s, k, h, B2_BIKE]), 0.2, places=6)
        self.assertAlmostEqual(float(r.decision[s, k, h, B2_DOCK]), 0.1, places=6)
        self.assertEqual(r.outcome[s, 0, h, 1], 1)
        self.assertEqual(r.outcome[s, k, h, 0], 0)
        self.assertTrue(np.isnan(r.decision[s, k, HORIZONS.index(30)]).all())
        self.assertTrue(np.isnan(r.decision[r.stations.index("chicago:3")]).all())

    def test_missing_label_keeps_decision_but_hides_outcome(self):
        path = self.data / "processed/final_pipeline_v1/labels/chicago_1_tune.parquet"
        t = pq.read_table(path)
        pq.write_table(
            t.filter(pa.compute.not_equal(t["row_id"], f"chicago:1|{TUNE0 + 600}|10")),
            path,
        )
        r = self.load("tune")
        self.assertTrue(np.isnan(r.outcome[0, 1, 0]).all())
        self.assertFalse(np.isnan(r.decision[0, 1, 0, BIKES]))

    def test_tune_requests_use_heldout_tables(self):
        r = self.load("tune")
        self.assertEqual(
            [(q.origin, q.dest, q.version) for q in r.requests], [(1, 0, "heldout")]
        )
        ride = r.ride["heldout"]
        self.assertEqual(ride[0, 1], 500.0)
        expected = 1.3 * haversine(STATIONS["chicago:2"], STATIONS["chicago:1"]) / 4
        self.assertAlmostEqual(ride[1, 0], expected, places=3)

    def test_training_requests_use_their_own_week_tables(self):
        r = self.load("train")
        self.assertEqual(
            [(q.origin, q.dest, q.version) for q in r.requests],
            [(0, 1, "train_week_2")],
        )
        self.assertEqual(r.ride["train_week_2"][0, 1], 402.0)
        k = (T0 + 2 * WEEK + 3600 - GRID0) // 600
        self.assertAlmostEqual(float(r.decision[0, k, 0, B2_BIKE]), 1 - 0.52, places=6)
        self.assertTrue(
            np.isnan(r.decision[0, 5, 0, P_BIKE])
        )  # week 0 has no forward score

    def test_default_scores_are_the_forecaster_outputs(self):
        """Without a scores path, train and tune read what build_forward_predictions.py
        and train_forecaster.py write; tune takes the calibrated LGBM column."""
        models = self.data / "models/forecaster_v0_m3"
        models.mkdir(parents=True)
        shutil.copy(
            self.data / "scores_train.parquet",
            models / "forward_train_predictions.parquet",
        )
        tune = pq.read_table(self.data / "scores_tune.parquet")
        decoy = pa.array(np.full(tune.num_rows, 0.99))
        pq.write_table(
            pa.table(
                {
                    "row_id": tune["row_id"],
                    "p_bike_unavailable_B1": decoy,
                    "p_bike_unavailable_LGBM_raw": decoy,
                    "p_bike_unavailable_LGBM": tune["p_bike_unavailable"],
                    "p_dock_unavailable_LGBM_raw": decoy,
                    "p_dock_unavailable_LGBM": tune["p_dock_unavailable"],
                }
            ),
            models / "tune_predictions.parquet",
        )
        for split in ("train", "tune"):
            np.testing.assert_array_equal(
                load_replay(self.data, self.project, split).decision,
                self.load(split).decision,
            )

    def test_calibration_split_is_refused(self):
        with self.assertRaisesRegex(ValueError, "calibration"):
            load_replay(
                self.data,
                self.project,
                "calibration",
                self.data / "scores_tune.parquet",
            )


if __name__ == "__main__":
    unittest.main()
