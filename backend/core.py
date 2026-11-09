"""Decision-only trip planning. No imports of replay outcomes or labels."""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
HORIZONS = (10, 20, 30, 40, 50, 60)


def registry():
    with (PROJECT / 'data/manifests/chicago/app_stations.csv').open(encoding='utf-8', newline='') as f:
        return [dict(id=r['station_id'], name=r['historical_name'], lat=float(r['historical_lat']),
                     lon=float(r['historical_lon']), live_id=r['current_station_id']) for r in csv.DictReader(f)]


def distance(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    v = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b['lon']-a['lon'])/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, v)))


def horizon(minutes):
    return max(10, int(math.ceil(minutes / 10 - 1e-9) * 10))


class Planner:
    def __init__(self, stations=None, od_path=None):
        self.stations = stations or registry()
        self.by_id = {s['id']: s for s in self.stations}
        self.od = {}
        path = od_path or PROJECT / 'reports/final_pipeline_audit/trip_od/planner_od.csv'
        if path.exists():
            with path.open(encoding='utf-8', newline='') as f:
                for r in csv.DictReader(f):
                    if r['method'] == 'training_median' and int(r['training_trips']) >= 20:
                        self.od[r['start_station_id'], r['end_station_id']] = float(r['ride_seconds']) / 60

    def endpoint(self, value):
        if isinstance(value, str):
            if value not in self.by_id:
                raise ValueError('unknown station')
            return self.by_id[value]
        point = dict(lat=value['lat'], lon=value['lon'])
        if min(distance(point, s) for s in self.stations) > 3000:
            raise ValueError('location must be within 3 km of the 32-station service area')
        return point

    def ride(self, a, b):
        if (a['id'], b['id']) in self.od:
            return self.od[a['id'], b['id']], 'training_median'
        return max(1, 1.3 * distance(a, b) / 4 / 60), 'geometric_estimate'

    def candidates(self, point, view, phase, limit):
        out = []
        for st in self.stations:
            state = view.get(st['id'])
            walk = distance(point, st) / 1.3 / 60
            if state and state.get(phase, False) and walk <= limit + 1e-9:
                out.append(dict(**st, walk_minutes=walk))
        return sorted(out, key=lambda s: (s['walk_minutes'], s['id']))[:3]

    @staticmethod
    def probability(state, h, phase, method):
        if h not in HORIZONS:
            return None
        key = 'p_bike' if phase == 'pickup' else 'p_dock'
        if method == 'B1':
            return float(state['bikes' if phase == 'pickup' else 'docks'] > 0)
        table = state.get('b2' if method == 'B2' else 'forecast', {})
        return table.get(h, table.get(str(h), {})).get(key)

    def plan(self, request, snapshot, policy=None):
        q = datetime.fromisoformat(snapshot['decision_time'])
        depart = request['departure_time']
        lead = (depart - q).total_seconds() / 60
        origin, dest = self.endpoint(request['origin']), self.endpoint(request['destination'])
        if distance(origin, dest) < 1:
            raise ValueError('origin and destination must differ')
        states = {s['id']: s for s in snapshot['stations']}
        requested = request['method']
        warnings = list(snapshot.get('warnings', []))
        method = requested
        if requested == 'RL':
            method = 'B3'
        if snapshot.get('stale') or not states:
            return self.no_plan(requested, 'Status is stale or unavailable; predictions are suppressed.', warnings)
        if method == 'B3' and snapshot['active_method'] == 'B2_historical':
            method = 'B2'
            warnings.append('Forecaster unavailable; using training-only historical rates (B2).')
        if method in ('B2', 'B3') and snapshot['active_method'] == 'unavailable':
            return self.no_plan(requested, 'No forecast artifacts or historical rates are available.', warnings)
        pickups = self.candidates(origin, states, 'pickup', request['walk_limit_minutes'])
        returns = self.candidates(dest, states, 'return', request['walk_limit_minutes'])
        if not pickups or not returns:
            return self.no_plan(requested, 'No operational candidates within the walking limit. Move an endpoint or increase the limit.', warnings)
        rl_pickup = None
        rl_wait = 0
        if requested == 'RL':
            try:
                if snapshot['mode'] == 'fixture' or policy is None:
                    raise ValueError('RL requires real model artifacts and decision data')
                if method != 'B3' or snapshot['active_method'] != 'lightgbm_sigmoid':
                    raise ValueError('RL requires calibrated forecaster probabilities')
                if not isinstance(request['origin'], str) or abs(lead) > 0.1:
                    raise ValueError('RL current-action serving requires a station origin and departure at the decision grid time')
                slots = self.policy_slots(pickups, states, 'pickup')
                action = policy.choose(slots, request['walk_limit_minutes'])
                if action == 3:
                    # Recommend one bounded wait and ask for a fresh decision afterwards;
                    # do not run the policy on imagined future feature rows.
                    rl_wait = 10
                    warnings.append('RL recommends waiting 10 minutes. The station itinerary is provisional B3; refresh the plan after waiting.')
                else:
                    rl_pickup = pickups[action]['id']
                    warnings.append('PPO selects the current pickup action. Future return choices are provisional B3; replan at return time for a current-state policy decision.')
            except Exception as exc:
                warnings.append(f'RL unavailable; using {method}: {exc}.')
        pairs = []
        for p in pickups:
            if rl_pickup is not None and p['id'] != rl_pickup:
                continue
            for r in returns:
                if p['id'] == r['id']:
                    continue
                ride, ride_method = self.ride(p, r)
                for wait in (0, 10, 20) if method != 'B1' else (0,):
                    if rl_pickup is not None and wait != 0 or rl_wait and wait != rl_wait:
                        continue
                    pickup_min = lead + wait + p['walk_minutes']
                    return_min = pickup_min + ride
                    if return_min + r['walk_minutes'] > 60:
                        continue
                    ph, rh = horizon(pickup_min), horizon(return_min)
                    pb = self.probability(states[p['id']], ph, 'pickup', method)
                    pd = self.probability(states[r['id']], rh, 'return', method)
                    if pb is None or pd is None:
                        continue
                    # Same one-step reward terms as policies.greedy; no independence claim.
                    score = (1 - 1.5*(1-pb) - .02*p['walk_minutes'] +
                             1 - 1.5*(1-pd) - .02*r['walk_minutes'] - .01*wait)
                    pairs.append(dict(pickup=self.stop(p, states, pb, ph, pickup_min, q),
                                      dropoff=self.stop(r, states, pd, rh, return_min, q),
                                      wait_minutes=wait, ride_minutes=round(ride, 1), ride_method=ride_method,
                                      total_minutes=round(return_min + r['walk_minutes'] - lead, 1), score=score))
        if not pairs:
            return self.no_plan(requested, 'No plan fits the 60-minute forecast window with available predictions.', warnings)
        pairs.sort(key=lambda p: (-p['score'], p['total_minutes']))
        primary = pairs[0]
        # Alternatives are from the initial decision; never claim they are failure-state actions.
        backups = []
        seen = {(primary['pickup']['id'], primary['dropoff']['id'])}
        for pair in pairs[1:]:
            key = pair['pickup']['id'], pair['dropoff']['id']
            if key not in seen:
                backups.append(pair)
                seen.add(key)
            if len(backups) == 2:
                break
        for pair in [primary, *backups]:
            pair.pop('score')
        actual = 'RL_pickup+B3_return' if rl_pickup else 'RL_wait+B3_provisional' if rl_wait else method
        return dict(status='ok', requested_method=requested, actual_method=actual,
                    planner_version='decision-pair-v1', primary=primary, backups=backups,
                    backup_semantics='Alternatives at the current decision time; use /replan after a failed attempt.',
                    warnings=warnings, no_plan_reason=None)

    def policy_slots(self, candidates, states, phase, ride_from=None):
        slots = []
        for st in candidates:
            state = states[st['id']]
            move = st['walk_minutes'] if phase == 'pickup' else self.ride(ride_from, st)[0]
            h = horizon(move)
            p = self.probability(state, h, phase, 'B3')
            nxt = self.probability(state, h+10, phase, 'B3')
            b2 = self.probability(state, h, phase, 'B2')
            count = state['bikes' if phase == 'pickup' else 'docks']
            empty = count <= 0
            slots.append(dict(valid=p is not None, walk_minutes=st['walk_minutes'], horizon=h,
                              share=count/max(1, state.get('capacity', state['bikes']+state['docks'])),
                              empty_now=empty, p_fail=1-p if p is not None else 1,
                              p_next=1-nxt if nxt is not None else 1-p if p is not None else 1,
                              p_b2=1-b2 if b2 is not None else float(empty)))
        return slots

    @staticmethod
    def stop(st, states, p, h, arrival, q):
        state = states[st['id']]
        return dict(id=st['id'], name=st['name'], lat=st['lat'], lon=st['lon'],
                    walk_minutes=round(st['walk_minutes'], 1), probability=p,
                    bikes=state['bikes'], docks=state['docks'], data_age_seconds=state['data_age_seconds'],
                    horizon_minutes=h, estimated_arrival_time=(q+timedelta(minutes=arrival)).isoformat(),
                    effective_prediction_time=(q+timedelta(minutes=h)).isoformat())

    @staticmethod
    def no_plan(requested, reason, warnings):
        return dict(status='no_plan', requested_method=requested, actual_method='unavailable',
                    planner_version='decision-pair-v1', primary=None, backups=[], warnings=warnings,
                    no_plan_reason=reason)
