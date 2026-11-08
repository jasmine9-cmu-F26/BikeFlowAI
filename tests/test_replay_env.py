"""Replay environment semantics on a hand-built three-station replay."""

from pathlib import Path
import sys, unittest
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts/rl"))
from replay_env import Replay, ReplayEnv, Request, BIKES, DOCKS, P_BIKE

G0 = 1626070000
K = 30
A, B, C = 0, 1, 2
WALK_AB = 390 / 1.3 / 60  # minutes


def make_replay(ride=None, requests=None):
    # A and B are ~390 m apart (5 min walk); C is ~5 km east.
    coords = np.array(
        [[41.88, -87.63], [41.88, -87.63 + 390 / 82_900], [41.88, -87.57]]
    )
    decision = np.zeros((3, K, 6, 8), np.float32)
    decision[..., :] = [5, 5, 10, 1, 0.1, 0.1, 0.2, 0.2]
    outcome = np.zeros((3, K, 6, 2), np.float32)
    if ride is None:
        ride = np.array([[600, 300, 1200], [300, 600, 1300], [1200, 1300, 600]], float)
    if requests is None:
        requests = [
            Request(origin=A, dest=C, time=G0 + 3 * 600 + 100, day=0, version="v")
        ]
    return Replay(
        ["chicago:A", "chicago:B", "chicago:C"],
        coords,
        G0,
        decision,
        outcome,
        {"v": ride},
        requests,
    )


def run(env, actions, request=0):
    env.reset(options={"request": request})
    total, info = 0.0, {}
    for a in actions:
        _, r, done, _, info = env.step(a)
        total += r
        if done:
            break
    return total, info


class ReplayEnvTests(unittest.TestCase):
    def env(self, replay=None, **kw):
        return ReplayEnv(replay or make_replay(), lam=0.02, mu=0.01, c=0.5, **kw)

    def test_first_decision_is_last_grid_point_ten_minutes_before_checkout(self):
        env = self.env()
        env.reset(options={"request": 0})
        self.assertEqual(env.t, G0 + 2 * 600)

    def test_pickup_candidates_are_origin_then_stations_within_walk_limit(self):
        env = self.env()
        env.reset(options={"request": 0})
        self.assertEqual([s["station"] for s in env.slots() if s["exists"]], [A, B])
        self.assertEqual(env.action_masks().tolist(), [True, True, False, True])

    def test_direct_trip_succeeds_with_reward_one(self):
        total, info = run(self.env(), [0, 0])
        self.assertEqual(info["outcome"], "success")
        self.assertAlmostEqual(total, 1.0)

    def test_failed_pickup_walks_to_backup_from_the_failed_station(self):
        replay = make_replay()
        replay.outcome[A, 2, 0, 0] = 1  # A empty at q0 + 10 min
        env = self.env(replay)
        env.reset(options={"request": 0})
        env.step(0)
        self.assertEqual(env.t, G0 + 3 * 600)
        self.assertEqual(env.action_masks().tolist(), [False, True, False, True])
        env.step(1)
        _, r, done, _, info = env.step(0)
        self.assertTrue(done)
        self.assertEqual(info["outcome"], "success")
        self.assertAlmostEqual(info["walk_minutes"], WALK_AB, places=1)
        self.assertAlmostEqual(info["reward"], 1 - 0.02 * info["walk_minutes"], places=6)

    def test_trying_every_candidate_without_a_bike_is_a_failure(self):
        replay = make_replay()
        replay.outcome[:, :, :, 0] = 1
        total, info = run(self.env(replay), [0, 1])
        self.assertEqual(info["outcome"], "failure")
        self.assertAlmostEqual(total, -0.5 - 0.02 * info["walk_minutes"], places=6)

    def test_failed_return_rides_on_to_next_candidate(self):
        replay = make_replay(
            requests=[
                Request(origin=C, dest=A, time=G0 + 3 * 600 + 100, day=0, version="v")
            ]
        )
        replay.outcome[A, 3, 1, 1] = (
            1  # A full when arriving 20 min after pickup at q0+10
        )
        env = self.env(replay)
        total, info = run(env, [0, 0, 1])
        self.assertEqual(info["outcome"], "success")
        self.assertEqual(info["failures"], 1)
        self.assertAlmostEqual(total, 1 - 0.02 * WALK_AB, places=2)

    def test_missing_outcome_row_ends_as_unobservable(self):
        replay = make_replay()
        replay.outcome[A, 2, 0, :] = np.nan
        total, info = run(self.env(replay), [0])
        self.assertEqual(info["outcome"], "unobservable")
        self.assertEqual(total, 0.0)

    def test_waiting_is_limited_and_only_before_pickup(self):
        env = self.env()
        env.reset(options={"request": 0})
        env.step(3)
        env.step(3)
        self.assertFalse(env.action_masks()[3])
        self.assertAlmostEqual(env.wait_minutes, 20)
        env.step(0)
        self.assertEqual(env.phase, "return")
        self.assertFalse(env.action_masks()[3])

    def test_return_slots_beyond_sixty_minutes_are_masked(self):
        ride = np.array([[600, 300, 4000], [300, 600, 4000], [4000, 4000, 600]], float)
        total, info = run(self.env(make_replay(ride=ride)), [0, 0])
        self.assertEqual(info["outcome"], "unobservable")

    def test_observations_and_slots_never_depend_on_outcomes(self):
        good, bad = make_replay(), make_replay()
        bad.outcome[:] = 1
        e1, e2 = self.env(good), self.env(bad)
        o1, _ = e1.reset(options={"request": 0})
        o2, _ = e2.reset(options={"request": 0})
        self.assertEqual(o1.shape, (31,))
        np.testing.assert_array_equal(o1, o2)
        self.assertEqual(e1.slots(), e2.slots())

    def test_slot_view_carries_current_stock_and_probabilities(self):
        replay = make_replay()
        replay.decision[B, 2, 0, BIKES] = 0
        replay.decision[B, 2, 0, P_BIKE] = 0.7
        env = self.env(replay)
        env.reset(options={"request": 0})
        b = env.slots()[1]
        self.assertTrue(b["empty_now"])
        self.assertAlmostEqual(b["p_forecast"], 0.7, places=6)
        self.assertEqual(b["horizon"], 10)
        self.assertEqual(replay.decision[B, 2, 0, DOCKS], 5)

    def test_masked_action_ends_the_episode_as_invalid(self):
        total, info = run(self.env(), [2])
        self.assertEqual(info["outcome"], "invalid")
        self.assertEqual(total, -0.5)

    def test_environment_passes_the_gymnasium_checker(self):
        from gymnasium.utils.env_checker import check_env

        check_env(self.env(), skip_render_check=True)


if __name__ == "__main__":
    unittest.main()
