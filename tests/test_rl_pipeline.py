"""Forecaster outputs to PPO and evaluation CLIs, on synthetic tables.

The score files follow the layouts that build_forward_predictions.py and
train_forecaster.py write, at their default paths, so this checks the contract
between the forecaster and the replay. PPO and the evaluator run as child
processes, as `make pipeline` does.
"""

from pathlib import Path
import csv, importlib.util, json, shutil, subprocess, sys, tempfile, unittest
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT = Path(__file__).resolve().parents[1]
HAVE_PPO = importlib.util.find_spec("sb3_contrib") is not None
STATIONS = {"chicago:1": (41.88, -87.63), "chicago:2": (41.88, -87.6253)}
DAY, WEEK = 86400, 7 * 86400
T0 = 1620018000  # 2021-05-03 05:00 UTC, train start in the pipeline contract
SPLITS = [("train", 0, 35), ("tune", 35, 39)]
TUNE_METHODS = ("B1", "B1cal", "B2", "LGBM_raw", "LGBM")


def write_tables(root, seed=0, step=600):
    """Features, labels and forecaster scores; low stock now means likely empty later."""
    rng = np.random.default_rng(seed)
    table = root / "processed/final_pipeline_v1"
    for sub in ["features", "labels", "B2"]:
        (table / sub).mkdir(parents=True)
    forward, tune = [], []
    for station in STATIONS:
        for split, lo, hi in SPLITS:
            q = np.arange(T0 + lo * DAY, T0 + hi * DAY - 3600, step, dtype=np.int64)
            n = len(q)
            feats, labels = [], []
            for h in [10, 30]:
                bikes = rng.integers(0, 6, n)
                risk = np.where(bikes <= 1, 0.7, 0.05)
                ids = [f"{station}|{t}|{h}" for t in q]
                keys = dict(
                    row_id=ids,
                    station_id=[station] * n,
                    request_time=q,
                    horizon_minutes=np.full(n, h, np.int16),
                )
                feats.append(
                    pa.table(
                        dict(
                            keys,
                            num_bikes_available=bikes,
                            num_docks_available=10 - bikes,
                            capacity=np.full(n, 10),
                            is_in_service=np.ones(n, bool),
                            split=[split] * n,
                        )
                    )
                )
                labels.append(
                    pa.table(
                        dict(
                            row_id=ids,
                            bike_unavailable=(rng.uniform(size=n) < risk).astype(
                                np.int8
                            ),
                            dock_unavailable=(rng.uniform(size=n) < 0.1).astype(
                                np.int8
                            ),
                        )
                    )
                )
                bike_p, dock_p = risk - 0.02, np.full(n, 0.1)
                if split == "train":
                    week = (q - T0) // WEEK
                    keep = week >= 2
                    forward.append(
                        pa.table(
                            {
                                k: np.asarray(v)[keep]
                                for k, v in dict(
                                    keys,
                                    fold_week=week,
                                    p_bike_unavailable=bike_p,
                                    p_dock_unavailable=dock_p,
                                ).items()
                            }
                        )
                    )
                else:
                    cols = dict(keys)
                    for m in TUNE_METHODS:
                        cols[f"p_bike_unavailable_{m}"] = (
                            bike_p if m == "LGBM" else np.full(n, 0.5)
                        )
                        cols[f"p_dock_unavailable_{m}"] = (
                            dock_p if m == "LGBM" else np.full(n, 0.5)
                        )
                    tune.append(pa.table(cols))
            name = station.replace(":", "_")
            pq.write_table(
                pa.concat_tables(feats), table / f"features/{name}_{split}.parquet"
            )
            pq.write_table(
                pa.concat_tables(labels), table / f"labels/{name}_{split}.parquet"
            )
    models = root / "models/forecaster_v0_m3"
    models.mkdir(parents=True)
    pq.write_table(
        pa.concat_tables(forward), models / "forward_train_predictions.parquet"
    )
    pq.write_table(pa.concat_tables(tune), models / "tune_predictions.parquet")
    return table


def add_replay_tables(table):
    cells = [(s, w, h) for s in STATIONS for w in range(7) for h in range(24)]
    rates = dict(bike_available_rate=0.8, dock_available_rate=0.9)
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(station_id=s, weekday=w, hour=h, version="heldout_final", **rates)
                for s, w, h in cells
            ]
        ),
        table / "B2/heldout_training_fit_rates.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    station_id=s, weekday=w, hour=h, version=f"train_week_{v}", **rates
                )
                for v in range(5)
                for s, w, h in cells
            ]
        ),
        table / "B2/training_expanding_week_rates.parquet",
    )
    (table / "OD").mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    start_station_id=a,
                    end_station_id=b,
                    version=f"train_week_{v}",
                    method="training_median",
                    ride_seconds=1700.0,
                )
                for v in range(5)
                for a in STATIONS
                for b in STATIONS
                if a != b
            ]
        ),
        table / "OD/training_expanding_week_od.parquet",
    )
    times = [
        (T0 + d * DAY + 600 * m + 700, split)
        for d, split in ((1, "train"), (15, "train"), (22, "train"), (29, "train"), (36, "tune"))
        for m in range(0, 120, 7)
    ]
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    start_station_id=a,
                    end_station_id=b,
                    request_time=t,
                    split=split,
                    replay_15min_request_retained=True,
                )
                for t, split in times
                for a, b in (("chicago:1", "chicago:2"), ("chicago:2", "chicago:1"))
            ]
        ),
        table / "mapped_app32_requests.parquet",
    )


def replay_project(root):
    """Station metadata and held-out ride times for the two synthetic stations."""
    project = root / "project"
    manifests = project / "data/manifests/chicago"
    manifests.mkdir(parents=True)
    shutil.copy(
        PROJECT / "data/manifests/chicago/final_pipeline_contract.json", manifests
    )
    with open(manifests / "app_stations.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station_id", "historical_lat", "historical_lon"])
        w.writerows([s, *ll] for s, ll in STATIONS.items())
    od = project / "reports/final_pipeline_audit/trip_od"
    od.mkdir(parents=True)
    with open(od / "planner_od.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start_station_id", "end_station_id", "method", "ride_seconds"])
        w.writerows(
            [a, b, "training_median", 1700.0]
            for a in STATIONS
            for b in STATIONS
            if a != b
        )
    return project


@unittest.skipUnless(
    HAVE_PPO, "sb3-contrib not installed (scripts/rl/requirements-ppo.txt)"
)
class PipelineSmokeTests(unittest.TestCase):
    def test_forecaster_outputs_to_rl_evaluation_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_replay_tables(write_tables(root))
            project = replay_project(root)
            ppo = root / "models/rl_dev/ppo.zip"
            common = ["--data-root", str(root), "--project-root", str(project)]
            run = dict(check=True, capture_output=True, text=True, timeout=600)
            subprocess.run(
                [
                    sys.executable,
                    str(PROJECT / "scripts/rl/train_ppo.py"),
                    *common,
                    "--steps",
                    "2048",
                    "--out",
                    str(ppo),
                ],
                **run,
            )
            reports = root / "rl_reports"
            subprocess.run(
                [
                    sys.executable,
                    str(PROJECT / "scripts/rl/evaluate.py"),
                    *common,
                    "--rl-model",
                    str(ppo),
                    "--reports",
                    str(reports),
                    "--bootstrap",
                    "20",
                ],
                **run,
            )
            with open(reports / "summary.csv", newline="") as f:
                summary = {r["policy"]: r for r in csv.DictReader(f)}
            manifest = json.loads((reports / "run_manifest.json").read_text())
            training = json.loads(ppo.with_suffix(".json").read_text())
        self.assertEqual(set(summary), {"B1", "B2", "B3", "RL"})
        self.assertGreater(int(summary["B3"]["observed"]), 0)
        self.assertEqual(manifest["split"], "tune")
        self.assertFalse(manifest["test_opened"])
        self.assertEqual(manifest["requests"], "grid")
        self.assertEqual(training["requests"], "grid")
        self.assertEqual(
            training["versions"], ["train_week_2", "train_week_3", "train_week_4"]
        )

    def test_lambda_sweep_retrains_and_compares_every_lambda(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_replay_tables(write_tables(root))
            project = replay_project(root)
            reports, models = root / "sweep", root / "models/sweep"
            subprocess.run(
                [
                    sys.executable,
                    str(PROJECT / "scripts/rl/sweep.py"),
                    "--data-root",
                    str(root),
                    "--project-root",
                    str(project),
                    "--lams",
                    "0.01",
                    "0.04",
                    "--seeds",
                    "0",
                    "1",
                    "--steps",
                    "2048",
                    "--jobs",
                    "2",
                    "--bootstrap",
                    "20",
                    "--models",
                    str(models),
                    "--reports",
                    str(reports),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=900,
            )
            with open(reports / "sweep_summary.csv", newline="") as f:
                summary = list(csv.DictReader(f))
            with open(reports / "sweep_comparisons.csv", newline="") as f:
                comparisons = list(csv.DictReader(f))
            manifest = json.loads((reports / "sweep_manifest.json").read_text())
            trained = {
                p.stem: json.loads(p.read_text())["lam"] for p in models.glob("*.json")
            }
            plotted = (reports / "frontier.png").exists()
        self.assertEqual(
            sorted((r["lam"], r["policy"], r["seed"]) for r in summary),
            sorted(
                (lam, p, s)
                for lam in ("0.01", "0.04")
                for p, s in (("B1", ""), ("B2", ""), ("B3", ""), ("RL", "0"), ("RL", "1"))
            ),
        )
        rl_vs_b3 = {
            (r["lam"], r["seed"], r["metric"])
            for r in comparisons
            if (r["policy_a"], r["policy_b"]) == ("RL", "B3")
        }
        self.assertEqual(
            rl_vs_b3,
            {
                (lam, s, m)
                for lam in ("0.01", "0.04")
                for s in ("0", "1")
                for m in ("success", "reward", "walk_minutes", "wait_minutes")
            },
        )
        self.assertEqual(
            trained,
            {
                "lam_0.01_seed_0": 0.01,
                "lam_0.01_seed_1": 0.01,
                "lam_0.04_seed_0": 0.04,
                "lam_0.04_seed_1": 0.04,
            },
        )
        self.assertEqual(
            (manifest["lams"], manifest["seeds"], manifest["requests"], manifest["split"]),
            ([0.01, 0.04], [0, 1], "grid", "tune"),
        )
        if importlib.util.find_spec("matplotlib"):
            self.assertTrue(plotted)


if __name__ == "__main__":
    unittest.main()
