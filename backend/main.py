"""Run: python -m uvicorn backend.main:app --port 8000"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .core import Planner, distance, horizon
from .providers import Providers, ZONE, local_time

logger = logging.getLogger('bikeflow.requests')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
logger.propagate = False
planner = Planner()


@asynccontextmanager
async def lifespan(app):
    app.state.providers = Providers()
    app.state.providers.start()
    yield
    app.state.providers.close()


app = FastAPI(title='BikeFlow AI', version='1.0.0', lifespan=lifespan)


class Point(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    origin: str | Point
    destination: str | Point
    departure_time: datetime
    historical_timestamp: datetime | None = None
    walk_limit_minutes: float = Field(default=5, ge=0, le=20)
    mode: Literal['fixture', 'replay', 'live'] = 'replay'
    method: Literal['B1', 'B2', 'B3', 'RL'] = 'B3'
    scenario: Literal['normal', 'model-missing', 'stale'] = 'normal'


class ReplanRequest(PlanRequest):
    failed_station_ids: list[str] = Field(default_factory=list, max_length=6)
    phase: Literal['pickup', 'return'] = 'pickup'


class Attempt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    station_id: str
    horizon_minutes: Literal[10, 20, 30, 40, 50, 60]
    phase: Literal['pickup', 'return']


class RevealRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    historical_timestamp: datetime
    attempts: list[Attempt] = Field(min_length=1, max_length=2)


@app.exception_handler(RequestValidationError)
async def invalid_request(_, exc):
    # Do not reflect or log raw coordinates / inputs from Pydantic errors.
    return JSONResponse(status_code=422, content={'detail': [dict(field='.'.join(str(x) for x in e['loc'][1:]), error=e['msg']) for e in exc.errors()]})


def error(field, message):
    raise HTTPException(422, detail=dict(field=field, error=message))


@app.get('/health')
def health():
    return app.state.providers.health()


@app.get('/registry')
def station_registry():
    return dict(stations=planner.stations)


@app.get('/stations')
def stations(mode: Literal['fixture', 'replay', 'live'] = 'replay', historical_timestamp: str | None = None,
             scenario: Literal['normal', 'model-missing', 'stale'] = 'normal'):
    if mode != 'live' and historical_timestamp is None:
        error('historical_timestamp', 'Required for replay and example modes.')
    try:
        snap = app.state.providers.snapshot(mode, local_time(historical_timestamp) if historical_timestamp else datetime.now(ZONE), scenario)
    except ValueError as exc:
        error('historical_timestamp', str(exc))
    return snap


@app.get('/demo/scenarios')
def scenarios():
    return dict(default_time='2021-07-20T08:00:00-05:00', timezone='America/Chicago', scenarios=[
        dict(id='normal', name='Morning commute', description='Synthetic station risk and alternative plans.'),
        dict(id='model-missing', name='Model fallback', description='Synthetic B2 fallback, clearly labeled.'),
        dict(id='stale', name='Stale data', description='Old counts remain visible; all predictions suppressed.')],
        replay_note='Use a prepared tune date. These presets are synthetic examples, not measured model results.')


def validate(req):
    q = datetime.now(ZONE) if req.mode == 'live' else req.historical_timestamp
    if q is None:
        error('historical_timestamp', 'Required in replay and example modes.')
    q, departure = local_time(q), local_time(req.departure_time)
    # Allow transport delay for a "depart now" request in live mode.
    if departure < q - timedelta(seconds=30 if req.mode == 'live' else 0):
        error('departure_time', 'Departure must not precede the decision clock.')
    if departure > q + timedelta(minutes=60):
        error('departure_time', 'Departure must be within the 60-minute forecast window.')
    values = req.model_dump()
    for field in ('origin', 'destination'):
        try:
            planner.endpoint(values[field])
        except ValueError as exc:
            error(field, str(exc))
    if distance(planner.endpoint(values['origin']), planner.endpoint(values['destination'])) < 1 and not (isinstance(req, ReplanRequest) and req.phase == 'return'):
        error('destination', 'Choose a different destination.')
    values['departure_time'] = max(departure, q)
    return q, values


def execute(req, replan=False):
    started = time.perf_counter()
    request_id = str(uuid.uuid4())
    outcome = 'error'
    actual = 'unavailable'
    age = None
    actions = []
    model_version = None
    try:
        q, values = validate(req)
        try:
            snap = app.state.providers.snapshot(req.mode, q, req.scenario)
        except ValueError as exc:
            error('historical_timestamp', str(exc))
        max_age = 300 if req.mode == 'live' else 900
        model_version = snap['model_version']
        age = max((s['data_age_seconds'] for s in snap['stations']), default=None)
        # Preserve old counts for map display, but never plan with stale stations.
        for s in snap['stations']:
            if s['data_age_seconds'] > max_age:
                s['pickup'] = s['return'] = False
        if replan:
            for sid in req.failed_station_ids:
                if sid not in planner.by_id:
                    error('failed_station_ids', 'Unknown station ID.')
            for s in snap['stations']:
                if s['id'] in req.failed_station_ids:
                    s['pickup' if req.phase == 'pickup' else 'return'] = False
        try:
            result = planner.plan(values, snap, app.state.providers.policy) if not replan or req.phase == 'pickup' else return_replan(values, snap)
        except ValueError as exc:
            error('destination', str(exc))
        outcome, actual = result['status'], result['actual_method']
        if result['primary']:
            route = result['primary']
            actions = [dict(phase=k, station_id=route[k]['id']) for k in ('pickup','dropoff') if route[k]]
        return dict(**result, request_id=request_id, mode=req.mode, decision_time=snap['decision_time'],
                    model_version=snap['model_version'], data_age_seconds=age,
                    latency_ms=round((time.perf_counter()-started)*1000, 1))
    finally:
        logger.info(json.dumps(dict(request_id=request_id, mode=req.mode, requested_method=req.method, actual_method=actual,
                                    status=outcome, planner_version='decision-pair-v1',
                                    actions=actions, model_version=model_version,
                                    latency_ms=round((time.perf_counter()-started)*1000, 1), data_age_seconds=age)))


def return_replan(values, snap):
    """Rider already has a bike: route to an untried dock from current position."""
    q = datetime.fromisoformat(snap['decision_time'])
    source, destination = planner.endpoint(values['origin']), planner.endpoint(values['destination'])
    states = {s['id']: s for s in snap['stations']}
    method = values['method']
    warnings = list(snap['warnings'])
    if method == 'RL':
        method = 'B3'
    if method == 'B3' and snap['active_method'] == 'B2_historical':
        method = 'B2'
    if snap['stale'] or (method != 'B1' and snap['active_method'] == 'unavailable'):
        return planner.no_plan(values['method'], 'No fresh return predictions available.', warnings)
    candidates = planner.candidates(destination, states, 'return', values['walk_limit_minutes'])
    rl_station = None
    if values['method'] == 'RL':
        try:
            if snap['mode'] == 'fixture' or snap['active_method'] != 'lightgbm_sigmoid' or 'id' not in source:
                raise ValueError('Real forecasts and a station current position are required')
            if abs((values['departure_time']-q).total_seconds()) > 6:
                raise ValueError('PPO requires departure at the current decision grid')
            if values.get('failed_station_ids'):
                raise ValueError('Failure-state PPO requires original slot history; using greedy replanning')
            action = app.state.providers.policy.choose(planner.policy_slots(candidates, states, 'return', source),
                                                       values['walk_limit_minutes'], phase='return')
            rl_station = candidates[action]['id']
        except Exception as exc:
            warnings.append(f'RL return action unavailable; using {method}: {exc}.')
    choices = []
    for st in candidates:
        if rl_station is not None and st['id'] != rl_station:
            continue
        # Arbitrary rider coordinates cannot use a station OD median.
        ride, source_method = planner.ride(source, st) if 'id' in source else (max(1, 1.3*distance(source, st)/4/60), 'geometric_estimate')
        arrival = max(0, (values['departure_time']-q).total_seconds()/60)+ride
        if arrival+st['walk_minutes'] > 60:
            continue
        h = horizon(arrival)
        p = planner.probability(states[st['id']], h, 'return', method)
        if p is not None:
            choices.append((1-1.5*(1-p)-.02*st['walk_minutes'], dict(pickup=None,
                           dropoff=planner.stop(st, states, p, h, arrival, q), wait_minutes=0,
                           ride_minutes=round(ride, 1), ride_method=source_method, total_minutes=round(ride+st['walk_minutes'], 1))))
    choices.sort(key=lambda c: -c[0])
    if not choices:
        return planner.no_plan(values['method'], 'No untried return station fits the constraints.', warnings)
    return dict(status='ok', requested_method=values['method'], actual_method='RL_return' if rl_station else method, planner_version='decision-pair-v1',
                primary=choices[0][1], backups=[c[1] for c in choices[1:3]], warnings=warnings, no_plan_reason=None,
                backup_semantics='Return-phase alternatives from the current decision clock.')


@app.post('/plan')
def plan(req: PlanRequest):
    return execute(req)


@app.post('/replan')
def replan(req: ReplanRequest):
    return execute(req, True)


@app.post('/replay/reveal')
def reveal(req: RevealRequest):
    for attempt in req.attempts:
        if attempt.station_id not in planner.by_id:
            error('attempts.station_id', 'Unknown station ID.')
    try:
        return app.state.providers.reveal(req.historical_timestamp, [a.model_dump() for a in req.attempts])
    except (ValueError, FileNotFoundError) as exc:
        error('historical_timestamp', str(exc))
