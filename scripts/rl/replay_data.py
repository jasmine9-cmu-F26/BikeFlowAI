"""Build a Replay for one split from the audited final_pipeline_v1 tables.

Decision fields come from features/, forecaster scores and B2 rates; outcome
fields come from labels/. Training weeks use their own past-only versions of
scores, B2 and ride times; tune and test use the held-out versions.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pyarrow.parquet as pq

from replay_env import HORIZONS, STEP, Replay, Request, first_decision_time

ZONE = ZoneInfo("America/Chicago")

WEEK = 7 * 86400
FIRST_SCORED_WEEK = 2
DETOUR, RIDE_SPEED = 1.3, 4.0  # geometric ride-time fallback, as in planner_od.csv
SPLITS = ("train", "tune", "test")


def default_scores(data_root, split):
    """Where build_forward_predictions.py (train) and train_forecaster.py (tune) write.

    Test scores must come from the final forecaster, whose calibrator is refit
    on the calibration split; nothing writes that file yet.
    """
    models = Path(data_root) / "models"
    return {
        "train": models / "forecaster_v0_m3/forward_train_predictions.parquet",
        "tune": models / "forecaster_v0_m3/tune_predictions.parquet",
        "test": models / "forecaster_final/predictions_test.parquet",
    }[split]


def score_column(path, target):
    """`p_<target>_unavailable`, or the calibrated `_LGBM` column of tune_predictions.parquet."""
    names = pq.read_schema(path).names
    for name in (f"p_{target}_unavailable", f"p_{target}_unavailable_LGBM"):
        if name in names:
            return name
    raise KeyError(f"{path} has no {target} probability column")


def train_start(project):
    contract = json.loads(
        (
            Path(project) / "data/manifests/chicago/final_pipeline_contract.json"
        ).read_text()
    )
    start = next(s for s in contract["chronological_splits"] if s["split"] == "train")[
        "start_utc"
    ]
    return int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp())


def files(table, kind, split):
    """DuckDB list literal of every `<kind>/*_<split>.parquet` part, sorted."""
    found = sorted((table / kind).glob(f"*_{split}.parquet"))
    if not found:
        raise FileNotFoundError(f"no {kind} parts for split {split} under {table}")
    return "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in found) + "]"


def local_days(epochs):
    unique, inverse = np.unique(np.asarray(epochs, np.int64), return_inverse=True)
    return np.array(
        [datetime.fromtimestamp(int(t), ZONE).date().toordinal() for t in unique]
    )[inverse]


def local_cells(epochs):
    """Chicago-local (weekday, hour) per epoch, matching the B2 fit in build_audited_features."""
    unique, inverse = np.unique(np.asarray(epochs, np.int64), return_inverse=True)
    cells = np.array(
        [
            (d.weekday(), d.hour)
            for d in (datetime.fromtimestamp(int(t), ZONE) for t in unique)
        ],
        np.int64,
    )
    return cells[inverse].reshape(-1, 2)


def week_version(t, start):
    return f"train_week_{(int(t) - start) // WEEK}"


def ride_matrix(rows, index, meters):
    """Training medians where supported, else 1.3 x straight line at 4 m/s."""
    ride = DETOUR * meters / RIDE_SPEED
    for r in rows:
        a, b = index.get(r["start_station_id"]), index.get(r["end_station_id"])
        seconds = r.get("ride_seconds")
        if a is None or b is None or seconds in (None, ""):
            continue
        if r.get("method", "training_median") == "training_median":
            ride[a, b] = float(seconds)
    return ride


def load_replay(data_root, project, split, scores=None):
    if split not in SPLITS:
        raise ValueError(
            f"replay is defined for {SPLITS}; {split} is reserved for forecaster calibration"
        )
    data_root, project = Path(data_root), Path(project)
    table = data_root / "processed/final_pipeline_v1"
    scores = Path(scores or default_scores(data_root, split))
    with open(project / "data/manifests/chicago/app_stations.csv", newline="") as f:
        meta = sorted(csv.DictReader(f), key=lambda r: r["station_id"])
    stations = [r["station_id"] for r in meta]
    index = {s: i for i, s in enumerate(stations)}
    coords = np.array(
        [[float(r["historical_lat"]), float(r["historical_lon"])] for r in meta]
    )
    start = train_start(project)

    cols = (
        duckdb.connect()
        .execute(
            f"SELECT f.station_id, f.request_time, f.horizon_minutes, f.num_bikes_available, f.num_docks_available, "
            f"f.capacity, f.is_in_service, l.bike_unavailable, l.dock_unavailable, s.{score_column(scores, 'bike')} AS p_bike_unavailable, s.{score_column(scores, 'dock')} AS p_dock_unavailable "
            f"FROM read_parquet({files(table, 'features', split)}, union_by_name=true) f "
            f"LEFT JOIN read_parquet({files(table, 'labels', split)}, union_by_name=true) l USING (row_id) "
            f"LEFT JOIN read_parquet('{str(scores).replace(chr(39), chr(39) * 2)}') s USING (row_id)"
        )
        .fetchnumpy()
    )
    keep = np.array([s in index for s in cols["station_id"]])
    cols = {k: v[keep] for k, v in cols.items()}
    t = cols["request_time"].astype(np.int64)
    h = cols["horizon_minutes"].astype(np.int64)
    grid0 = int(t.min())
    if np.any((t - grid0) % STEP):
        raise ValueError("feature request times are not on one 10-minute grid")
    K = int((t.max() - grid0) // STEP) + 1
    s_ix = np.array([index[s] for s in cols["station_id"]])
    k_ix = (t - grid0) // STEP
    h_ix = np.array([HORIZONS.index(int(x)) for x in h])

    def num(name):
        v = cols[name]
        return (
            np.ma.asarray(v).astype(float).filled(np.nan)
            if v.dtype != object
            else np.array([np.nan if x is None else float(x) for x in v])
        )

    versions = (
        np.array([week_version(x, start) for x in t])
        if split == "train"
        else np.full(len(t), "heldout_final")
    )
    b2_path = table / (
        "B2/training_expanding_week_rates.parquet"
        if split == "train"
        else "B2/heldout_training_fit_rates.parquet"
    )
    rates = {
        (r["version"], r["station_id"], int(r["weekday"]), int(r["hour"])): (
            r["bike_available_rate"],
            r["dock_available_rate"],
        )
        for r in pq.read_table(b2_path).to_pylist()
    }
    cells = local_cells(t + 60 * h)
    b2 = np.array(
        [
            rates.get((v, s, int(w), int(hr)), (np.nan, np.nan))
            for v, s, (w, hr) in zip(versions, cols["station_id"], cells)
        ],
        float,
    )

    decision = np.full((len(stations), K, len(HORIZONS), 8), np.nan, np.float32)
    outcome = np.full((len(stations), K, len(HORIZONS), 2), np.nan, np.float32)
    decision[s_ix, k_ix, h_ix] = np.column_stack(
        [
            num("num_bikes_available"),
            num("num_docks_available"),
            num("capacity"),
            num("is_in_service"),
            num("p_bike_unavailable"),
            num("p_dock_unavailable"),
            1 - b2[:, 0],
            1 - b2[:, 1],
        ]
    )
    outcome[s_ix, k_ix, h_ix] = np.column_stack(
        [num("bike_unavailable"), num("dock_unavailable")]
    )

    probe = Replay(stations, coords, grid0, decision[:, :1], outcome[:, :1], {}, [])
    req = [
        r
        for r in pq.read_table(table / "mapped_app32_requests.parquet").to_pylist()
        if r["split"] == split
        and r["replay_15min_request_retained"]
        and r["start_station_id"] in index
        and r["end_station_id"] in index
    ]
    requests = []
    for r, day in zip(req, local_days([r["request_time"] for r in req]) if req else []):
        q0 = first_decision_time(probe, r["request_time"])
        if not 0 <= (q0 - grid0) // STEP < K:
            continue
        version = "heldout"
        if split == "train":
            week = (int(r["request_time"]) - start) // WEEK
            if week < FIRST_SCORED_WEEK:
                continue
            version = f"train_week_{week}"
        requests.append(
            Request(
                index[r["start_station_id"]],
                index[r["end_station_id"]],
                int(r["request_time"]),
                int(day),
                version,
            )
        )
    requests.sort(key=lambda q: (q.time, q.origin, q.dest))

    meters = probe.meters
    if split == "train":
        od = pq.read_table(table / "OD/training_expanding_week_od.parquet").to_pylist()
        ride = {
            v: ride_matrix([r for r in od if r["version"] == v], index, meters.copy())
            for v in sorted({q.version for q in requests})
        }
    else:
        with open(
            project / "reports/final_pipeline_audit/trip_od/planner_od.csv", newline=""
        ) as f:
            ride = {
                "heldout": ride_matrix(list(csv.DictReader(f)), index, meters.copy())
            }
    return Replay(stations, coords, grid0, decision, outcome, ride, requests)
