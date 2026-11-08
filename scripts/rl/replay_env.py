"""One simulated rider replayed against audited station outcomes.

A `Replay` holds two aligned views indexed [station, grid step, horizon index]:
`decision` (what a policy may see at request time) and `outcome` (bike/dock
unavailable at arrival). `ReplayEnv` reads `outcome` only after an action is
fixed. See docs/rl_replay_design.md.
"""

from dataclasses import dataclass
import math

import gymnasium as gym
import numpy as np

STEP = 600  # feature grid spacing, seconds
HORIZONS = (10, 20, 30, 40, 50, 60)
WALK_SPEED = 1.3  # m/s, straight line
SLOTS = 3
WAIT = SLOTS  # action index
MAX_WAITS = 2
SLOT_FEATURES = 9
OBS_SIZE = SLOTS * SLOT_FEATURES + 4

# decision fields
BIKES, DOCKS, CAPACITY, IN_SERVICE, P_BIKE, P_DOCK, B2_BIKE, B2_DOCK = range(8)
PHASE_FIELDS = {
    "pickup": (BIKES, P_BIKE, B2_BIKE, 0),
    "return": (DOCKS, P_DOCK, B2_DOCK, 1),
}


@dataclass(frozen=True)
class Request:
    origin: int
    dest: int
    time: int  # real checkout, epoch seconds
    day: int  # Chicago-local ordinal, for bootstrap
    version: str  # ride-time table to use


@dataclass
class Replay:
    stations: list
    coords: np.ndarray  # (S, 2) lat, lon
    grid0: int
    decision: np.ndarray  # (S, K, 6, 8) float32, NaN = missing row
    outcome: np.ndarray  # (S, K, 6, 2) float32, NaN = missing row
    ride: dict  # version -> (S, S) seconds
    requests: list

    def __post_init__(self):
        lat, lon = np.radians(self.coords[:, 0]), np.radians(self.coords[:, 1])
        dlat, dlon = lat[:, None] - lat[None], lon[:, None] - lon[None]
        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(lat[:, None]) * np.cos(lat[None]) * np.sin(dlon / 2) ** 2
        )
        self.meters = 2 * 6_371_000 * np.arcsin(np.sqrt(a))
        self.walk_seconds = self.meters / WALK_SPEED

    def index(self, t, horizon):
        k, rem = divmod(int(t) - self.grid0, STEP)
        if rem or not 0 <= k < self.decision.shape[1] or horizon not in HORIZONS:
            return None
        return k, HORIZONS.index(horizon)

    def nearby(self, station, limit_minutes, slots=SLOTS):
        """The station itself, then others within the walk limit, nearest first."""
        walk = self.walk_seconds[station]
        others = [
            s
            for s in np.argsort(walk, kind="stable")
            if s != station and walk[s] <= 60 * limit_minutes
        ]
        return [station] + [int(s) for s in others[: slots - 1]]


def ceil_horizon(seconds):
    return max(10, 10 * math.ceil(seconds / STEP - 1e-9))


def first_decision_time(replay, checkout):
    return replay.grid0 + STEP * ((int(checkout) - STEP - replay.grid0) // STEP)


class ReplayEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, replay, lam=0.02, mu=0.01, c=0.5, walk_limit=10, seed=None):
        self.replay, self.lam, self.mu, self.c, self.walk_limit = (
            replay,
            lam,
            mu,
            c,
            walk_limit,
        )
        self.observation_space = gym.spaces.Box(-1.0, 10.0, (OBS_SIZE,), np.float32)
        self.action_space = gym.spaces.Discrete(SLOTS + 1)
        self._rng = np.random.default_rng(seed)

    # ----- episode state -----
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        i = (options or {}).get("request")
        if i is None:
            i = int(self._rng.integers(len(self.replay.requests)))
        self.request = self.replay.requests[i]
        self.t0 = self.t = first_decision_time(self.replay, self.request.time)
        self.phase, self.here = "pickup", self.request.origin
        self.candidates = self.replay.nearby(self.request.origin, self.walk_limit)
        self.tried, self.waits, self.failures = set(), 0, 0
        self.walk_minutes = self.wait_minutes = self.total = 0.0
        return self.observation(), {}

    def _move_seconds(self, station):
        r = self.replay
        if self.phase == "pickup":
            return r.walk_seconds[self.here, station]
        return r.ride[self.request.version][self.here, station]

    def slots(self):
        """Decision-view description of each slot; never reads outcomes."""
        bikes_or_docks, p_col, b2_col, _ = PHASE_FIELDS[self.phase]
        out = []
        for j in range(SLOTS):
            slot = dict(exists=j < len(self.candidates), valid=False)
            if slot["exists"]:
                s = self.candidates[j]
                move = float(self._move_seconds(s))
                h = ceil_horizon(move)
                walk = (
                    move / 60
                    if self.phase == "pickup"
                    else self.replay.walk_seconds[s, self.request.dest] / 60
                )
                slot.update(
                    station=s,
                    horizon=h,
                    walk_minutes=float(walk),
                    tried=s in self.tried,
                )
                row = self._row(s, h)
                if row is not None:
                    nxt = self._row(s, h + 10)
                    cap = row[CAPACITY]
                    slot.update(
                        count=float(row[bikes_or_docks]),
                        share=float(row[bikes_or_docks] / cap) if cap > 0 else 0.0,
                        empty_now=bool(
                            row[bikes_or_docks] <= 0 or row[IN_SERVICE] < 0.5
                        ),
                        p_forecast=float(row[p_col]),
                        p_forecast_next=float(nxt[p_col]) if nxt is not None else None,
                        p_b2=float(row[b2_col]) if not np.isnan(row[b2_col]) else None,
                        p_b2_next=float(nxt[b2_col])
                        if nxt is not None and not np.isnan(nxt[b2_col])
                        else None,
                    )
                slot["valid"] = row is not None and not slot["tried"]
            out.append(slot)
        return out

    def _row(self, station, horizon):
        ix = self.replay.index(self.t, horizon)
        if ix is None:
            return None
        row = self.replay.decision[station, ix[0], ix[1]]
        p_col = PHASE_FIELDS[self.phase][1]
        return None if np.isnan(row[BIKES]) or np.isnan(row[p_col]) else row

    def action_masks(self):
        mask = [s["valid"] for s in self.slots()]
        return np.array(
            mask + [self.phase == "pickup" and self.waits < MAX_WAITS], bool
        )

    def observation(self):
        obs = np.zeros(OBS_SIZE, np.float32)
        for j, s in enumerate(self.slots()):
            if not s["exists"]:
                continue
            base = j * SLOT_FEATURES
            obs[base + 8] = float(s["tried"])
            if "p_forecast" not in s:
                continue
            p_next = (
                s["p_forecast_next"]
                if s["p_forecast_next"] is not None
                else s["p_forecast"]
            )
            b2 = s["p_b2"] if s["p_b2"] is not None else float(s["empty_now"])
            obs[base : base + 8] = [
                float(s["valid"]),
                s["walk_minutes"] / 10,
                s["horizon"] / 60,
                s["share"],
                float(s["empty_now"]),
                s["p_forecast"],
                p_next,
                b2,
            ]
        obs[-4:] = [
            float(self.phase == "return"),
            self.waits / MAX_WAITS,
            (self.t - self.t0) / 3600,
            self.failures / 3,
        ]
        return obs

    # ----- transitions -----
    def _finish(self, reward, outcome):
        self.total += reward
        info = dict(
            outcome=outcome,
            reward=self.total,
            walk_minutes=self.walk_minutes,
            wait_minutes=self.wait_minutes,
            failures=self.failures,
            phase=self.phase,
        )
        return self.observation(), reward, True, False, info

    def _continue(self, reward):
        mask = self.action_masks()
        if all(s in self.tried for s in self.candidates):
            return self._finish(reward - self.c, "failure")
        if not mask.any():
            return self._finish(reward, "unobservable")
        self.total += reward
        return self.observation(), reward, False, False, {}

    def step(self, action):
        action = int(action)
        if not self.action_masks()[action]:
            return self._finish(-self.c, "invalid")
        if action == WAIT:
            self.waits += 1
            self.wait_minutes += STEP / 60
            self.t += STEP
            return self._continue(-self.mu * STEP / 60)
        slot = self.slots()[action]
        s, h = slot["station"], slot["horizon"]
        reward = 0.0
        if self.phase == "pickup":
            self.walk_minutes += slot["walk_minutes"]
            reward -= self.lam * slot["walk_minutes"]
        k, hi = self.replay.index(self.t, h)
        failed = self.replay.outcome[s, k, hi, PHASE_FIELDS[self.phase][3]]
        if np.isnan(failed):
            return self._finish(reward, "unobservable")
        self.t += 60 * h
        self.here = s
        if failed >= 0.5:
            self.failures += 1
            self.tried.add(s)
            return self._continue(reward)
        if self.phase == "pickup":
            self.phase, self.tried = "return", set()
            self.candidates = self.replay.nearby(self.request.dest, self.walk_limit)
            return self._continue(reward)
        self.walk_minutes += slot["walk_minutes"]
        reward += 1.0 - self.lam * slot["walk_minutes"]
        return self._finish(reward, "success")
