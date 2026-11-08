"""MaskablePPO on a replay where reward alone tells the origin from the backup.

Training runs in a child process: lightgbm and sklearn (loaded by the forecaster
tests in the same runner) bundle libomp, and a second OpenMP runtime next to
torch's crashes or deadlocks on macOS. Production keeps them in separate
processes too.
"""

from pathlib import Path
import importlib.util, json, subprocess, sys, tempfile, unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts/rl"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_replay_env import A, G0, make_replay
from replay_env import P_BIKE, Request

HAVE_PPO = importlib.util.find_spec("sb3_contrib") is not None


def learn_and_summarize():
    from evaluate import evaluate, summarize
    from train_ppo import load_policy, train

    requests = [Request(A, 2, G0 + 600 * k + 100, k, "v") for k in range(2, 14)]
    replay = make_replay(requests=requests)
    replay.decision[..., P_BIKE] = 0.5  # forecasts carry no information
    replay.outcome[A, :, :, 0] = 1
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ppo.zip"
        train(replay, path, steps=6144, lam=0.02, mu=0.01, c=0.5, seed=0)
        summary = summarize(evaluate(replay, {"RL": load_policy(path)}, 0.02, 0.01, 0.5))[0]
        summary["manifest_written"] = path.with_suffix(".json").exists()
    return summary


def child(code_or_flag):
    return subprocess.run([sys.executable, *code_or_flag], capture_output=True, text=True, timeout=300, check=True).stdout


class ProcessIsolationTests(unittest.TestCase):
    def test_replay_and_ppo_modules_do_not_load_lightgbm_or_sklearn(self):
        code = (
            "import sys; sys.path[:0] = [sys.argv[1]]; "
            "import replay_data, evaluate, policies, train_ppo; "
            "print(sorted(m for m in ('lightgbm', 'sklearn') if m in sys.modules))"
        )
        self.assertEqual(child(["-c", code, str(PROJECT / "scripts/rl")]).strip(), "[]")


@unittest.skipUnless(HAVE_PPO, "sb3-contrib not installed (scripts/rl/requirements-ppo.txt)")
class TrainPPOTests(unittest.TestCase):
    def test_policy_learns_to_skip_an_origin_that_never_has_bikes(self):
        summary = json.loads(child([__file__, "--child"]).strip().splitlines()[-1])
        self.assertTrue(summary["manifest_written"])
        self.assertEqual(summary["failed_attempts_mean"], 0.0)
        self.assertEqual(summary["success_rate"], 1.0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        print(json.dumps(learn_and_summarize()))
    else:
        unittest.main()
