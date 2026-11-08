"""Greedy B1/B2/B3 policies and the replay evaluator."""

from pathlib import Path
import sys, unittest
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts/rl"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_replay_env import A, B, G0, make_replay
from replay_env import B2_BIKE, P_BIKE, ReplayEnv, Request
from policies import greedy
from evaluate import compare, evaluate, summarize

K2 = 2  # grid index of the first decision


def first_action(replay, source):
    env = ReplayEnv(replay, lam=0.02, mu=0.01, c=0.5)
    obs, _ = env.reset(options={"request": 0})
    return greedy(source, lam=0.02, mu=0.01, c=0.5)(env, obs)


class GreedyTests(unittest.TestCase):
    def test_forecast_greedy_walks_away_from_a_likely_empty_station(self):
        replay = make_replay()
        replay.decision[A, K2, 0, P_BIKE] = 0.9
        replay.decision[B, K2, 0, P_BIKE] = 0.05
        self.assertEqual(first_action(replay, "B3"), 1)
        self.assertEqual(first_action(replay, "B1"), 0)

    def test_forecast_greedy_waits_when_the_next_slot_is_clearly_better(self):
        replay = make_replay()
        replay.decision[:, K2, :, P_BIKE] = 0.9
        replay.decision[A, K2, 1, P_BIKE] = 0.05  # arriving 10 minutes later
        self.assertEqual(first_action(replay, "B3"), 3)
        self.assertEqual(first_action(replay, "B1"), 0)

    def test_historical_greedy_reads_b2(self):
        replay = make_replay()
        replay.decision[A, K2, 0, B2_BIKE] = 0.95
        self.assertEqual(first_action(replay, "B2"), 1)

    def test_greedy_policies_never_choose_a_masked_action(self):
        rng = np.random.default_rng(0)
        requests = [Request(A, 2, G0 + 600 * k + 100, 0, "v") for k in range(2, 20)]
        for trial in range(5):
            replay = make_replay(requests=requests)
            replay.decision[..., P_BIKE:] = rng.uniform(
                size=replay.decision[..., P_BIKE:].shape
            )
            replay.decision[..., 0] = rng.integers(0, 3, replay.decision.shape[:3])
            replay.outcome[:] = rng.uniform(size=replay.outcome.shape) < 0.4
            rows = evaluate(
                replay,
                {s: greedy(s, 0.02, 0.01, 0.5) for s in ("B1", "B2", "B3")},
                0.02,
                0.01,
                0.5,
            )
            self.assertNotIn("invalid", {r["outcome"] for r in rows})


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.replay = make_replay(
            requests=[
                Request(A, 2, G0 + 3 * 600 + 100, 1, "v"),
                Request(A, 2, G0 + 9 * 600 + 100, 2, "v"),
            ]
        )
        self.replay.decision[A, :, 0, P_BIKE] = 0.9
        self.replay.outcome[A, :, 0, 0] = 1
        self.policies = {s: greedy(s, 0.02, 0.01, 0.5) for s in ("B1", "B3")}

    def test_every_policy_runs_every_request(self):
        rows = evaluate(self.replay, self.policies, 0.02, 0.01, 0.5)
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {(r["policy"], r["request"]) for r in rows},
            {(p, i) for p in ("B1", "B3") for i in (0, 1)},
        )

    def test_summary_counts_failed_attempts_and_success(self):
        summary = {
            r["policy"]: r
            for r in summarize(evaluate(self.replay, self.policies, 0.02, 0.01, 0.5))
        }
        self.assertEqual(summary["B1"]["success_rate"], 1.0)
        self.assertEqual(summary["B1"]["failed_attempts_mean"], 1.0)
        self.assertEqual(summary["B3"]["failed_attempts_mean"], 0.0)
        self.assertEqual(summary["B3"]["unobservable"], 0)

    def test_paired_comparison_uses_requests_observable_under_both(self):
        self.replay.outcome[B, 9, 0, 0] = np.nan
        rows = evaluate(self.replay, self.policies, 0.02, 0.01, 0.5)
        result = compare(rows, "B3", "B1", "reward", n=50, seed=0)
        self.assertEqual(result["paired_requests"], 1)
        self.assertEqual(result["days"], 1)
        self.assertAlmostEqual(result["difference"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
