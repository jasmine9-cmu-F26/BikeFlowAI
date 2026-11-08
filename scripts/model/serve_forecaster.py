"""Minimal FastAPI wrapper around the forecaster for integration (replay mode).

  BIKEFLOW_DATA_ROOT=EXT uvicorn serve_forecaster:app --app-dir scripts/model --port 8000
  GET /health
  GET /forecast?historical_timestamp=2021-07-20T08:00&station_id=...&station_id=...

Model files are loaded once at startup; inference never trains. A missing or
corrupted model starts the service degraded (B2); missing B2 -> unavailable.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from bikeflow_model import ZONE
from replay_forecast import build_service, forecast, load_request

DATA_ROOT = Path(os.environ.get('BIKEFLOW_DATA_ROOT', Path.home() / 'Documents/BikeFlowAI-data/divvy/chicago_historical_2021_sample'))
SERVICE = build_service(DATA_ROOT, os.environ.get('BIKEFLOW_SIMULATE') or None)
app = FastAPI(title='BikeFlow forecaster (replay)')


@app.get('/health')
def health():
    return dict(**SERVICE.status(), data_root_ready=(DATA_ROOT / 'processed/final_pipeline_v1/features').exists(), mode='replay')


@app.get('/forecast')
def get_forecast(historical_timestamp: str, station_id: list[str] | None = Query(default=None)):
    try:
        when = pd.Timestamp(historical_timestamp)
    except ValueError as exc:
        raise HTTPException(422, detail=dict(field='historical_timestamp', error=str(exc)))
    when = when.tz_localize(ZONE) if when.tzinfo is None else when
    try:
        df = load_request(DATA_ROOT, when, station_id)
    except SystemExit as exc:
        raise HTTPException(422, detail=dict(field='historical_timestamp', error=str(exc)))
    if df.empty:
        raise HTTPException(422, detail=dict(field='station_id', error='no app station matches'))
    return forecast(SERVICE, df)
