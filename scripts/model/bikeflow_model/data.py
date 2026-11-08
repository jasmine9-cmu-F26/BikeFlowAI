"""Load audited feature/label tables and convert them into model matrices.

Only `model_feature_columns` from the committed schema become model inputs.
Labels are joined on row_id for fitting/scoring only.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import ZONE

PROJECT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = PROJECT / 'reports/final_pipeline_audit/features/feature_schema.json'
LABEL_KEEP = ['row_id', 'target_time', 'target_offset_seconds', 'bike_unavailable', 'dock_unavailable']


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def feature_columns(schema: dict | None = None) -> list[str]:
    return list((schema or load_schema())['model_feature_columns'])


def pipeline_root(data_root: Path) -> Path:
    return Path(data_root) / 'processed/final_pipeline_v1'


def load_split(data_root: Path, splits: list[str], schema: dict | None = None) -> pd.DataFrame:
    """Return features joined to labels for the given chronological splits."""
    schema = schema or load_schema()
    root = pipeline_root(data_root)
    feats = feature_columns(schema)
    keep = ['row_id', 'split', 'request_time'] + [c for c in feats if c not in ('station_id', 'horizon_minutes')]
    con = duckdb.connect()
    con.execute('SET threads=4')
    marks = ','.join('?' for _ in splits)
    query = (
        f"SELECT f.station_id, f.horizon_minutes, {', '.join('f.' + c for c in keep)}, "
        f"{', '.join('l.' + c for c in LABEL_KEEP if c != 'row_id')} "
        f"FROM read_parquet(?) f JOIN read_parquet(?) l USING (row_id) "
        f"WHERE f.split IN ({marks}) ORDER BY f.request_time, f.station_id, f.horizon_minutes"
    )
    df = con.execute(query, [str(root / 'features/*.parquet'), str(root / 'labels/*.parquet'), *splits]).df()
    con.close()
    return add_derived(df)


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Columns derived only from request time and horizon (known at decision time)."""
    df = df.copy()
    target = pd.to_datetime(df['request_time'] + df['horizon_minutes'].astype(np.int64) * 60, unit='s', utc=True).dt.tz_convert(ZONE)
    df['target_weekday'] = target.dt.day_of_week.astype(np.int16)
    df['target_hour'] = target.dt.hour.astype(np.int16)
    request = pd.to_datetime(df['request_time'], unit='s', utc=True).dt.tz_convert(ZONE)
    df['service_day'] = request.dt.strftime('%Y-%m-%d')
    return df


def to_matrix(df: pd.DataFrame, columns: list[str], station_categories: list[str]) -> pd.DataFrame:
    """Numeric LightGBM matrix: native NaN kept, booleans as 0/1, station as train-fit category."""
    out = pd.DataFrame(index=df.index)
    for name in columns:
        col = df[name]
        if name == 'station_id':
            out[name] = pd.Categorical(col, categories=station_categories)
        elif col.dtype == object or str(col.dtype) == 'boolean':
            out[name] = pd.to_numeric(col.map({True: 1.0, False: 0.0}), errors='coerce').astype(float)
        else:
            out[name] = col.astype(float)
    return out
