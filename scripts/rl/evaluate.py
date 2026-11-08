"""Run policies on identical replay requests and compare them.

Development use reads the tune replay; --final reads test once, with settings
frozen beforehand. Outputs go to reports/rl_eval/<split>/.
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from policies import SOURCES, greedy
from replay_data import load_replay
from replay_env import ReplayEnv

OBSERVED = ("success", "failure")


def rollout(env, policy, request):
    obs, _ = env.reset(options={"request": request})
    while True:
        obs, _, done, _, info = env.step(policy(env, obs))
        if done:
            return info


def day_bootstrap(loss_a, loss_b, day, n=1000, seed=0):
    """Mean of loss_a - loss_b with a 95% percentile interval over resampled days."""
    diff = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    days, inverse = np.unique(day, return_inverse=True)
    sums = np.bincount(inverse, diff, len(days))
    counts = np.bincount(inverse, minlength=len(days)).astype(float)
    draws = np.random.default_rng(seed).integers(0, len(days), (n, len(days)))
    stats = sums[draws].sum(1) / counts[draws].sum(1)
    return (
        float(diff.mean()),
        float(np.percentile(stats, 2.5)),
        float(np.percentile(stats, 97.5)),
    )


def evaluate(replay, policies, lam, mu, c, walk_limit=10):
    """One row per (policy, request). A masked action is a policy bug, not a result."""
    env = ReplayEnv(replay, lam=lam, mu=mu, c=c, walk_limit=walk_limit)
    rows = []
    for name, policy in policies.items():
        for i, request in enumerate(replay.requests):
            info = rollout(env, policy, i)
            if info["outcome"] == "invalid":
                raise RuntimeError(
                    f"policy {name} chose a masked action on request {i}"
                )
            rows.append(
                dict(
                    policy=name,
                    request=i,
                    day=request.day,
                    origin=replay.stations[request.origin],
                    dest=replay.stations[request.dest],
                    checkout=request.time,
                    **info,
                )
            )
    return rows


def summarize(rows):
    out = []
    for name in dict.fromkeys(r["policy"] for r in rows):
        mine = [r for r in rows if r["policy"] == name]
        seen = [r for r in mine if r["outcome"] in OBSERVED]
        walk = (
            np.array([r["walk_minutes"] for r in seen]) if seen else np.array([np.nan])
        )
        def rate(pred, seen=seen):
            return float(np.mean([pred(r) for r in seen])) if seen else float("nan")
        out.append(
            dict(
                policy=name,
                requests=len(mine),
                observed=len(seen),
                unobservable=len(mine) - len(seen),
                success_rate=rate(lambda r: r["outcome"] == "success"),
                pickup_failure_rate=rate(
                    lambda r: r["outcome"] == "failure" and r["phase"] == "pickup"
                ),
                return_failure_rate=rate(
                    lambda r: r["outcome"] == "failure" and r["phase"] == "return"
                ),
                failed_attempts_mean=rate(lambda r: r["failures"]),
                walk_minutes_mean=float(walk.mean()),
                walk_minutes_median=float(np.median(walk)),
                walk_minutes_p90=float(np.percentile(walk, 90)),
                wait_minutes_mean=rate(lambda r: r["wait_minutes"]),
                reward_mean=rate(lambda r: r["reward"]),
            )
        )
    return out


def compare(rows, a, b, metric, n=1000, seed=0):
    """a - b on requests observed under both policies, with a Chicago-day bootstrap interval."""
    by = {(r["policy"], r["request"]): r for r in rows}
    paired = sorted(
        i
        for p, i in by
        if p == a
        and (b, i) in by
        and by[a, i]["outcome"] in OBSERVED
        and by[b, i]["outcome"] in OBSERVED
    )
    value = (
        (lambda r: float(r["outcome"] == "success"))
        if metric == "success"
        else (lambda r: float(r[metric]))
    )
    if not paired:
        return dict(
            policy_a=a,
            policy_b=b,
            metric=metric,
            paired_requests=0,
            days=0,
            difference=float("nan"),
            lo=float("nan"),
            hi=float("nan"),
        )
    diff, lo, hi = day_bootstrap(
        [value(by[a, i]) for i in paired],
        [value(by[b, i]) for i in paired],
        [by[a, i]["day"] for i in paired],
        n=n,
        seed=seed,
    )
    return dict(
        policy_a=a,
        policy_b=b,
        metric=metric,
        paired_requests=len(paired),
        days=len({by[a, i]["day"] for i in paired}),  # interval is degenerate with one day
        difference=diff,
        lo=lo,
        hi=hi,
    )


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def report(rows, out, manifest, pairs, n, seed):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "episodes.csv", rows)
    write_csv(out / "summary.csv", summarize(rows))
    comparisons = [
        compare(rows, a, b, m, n, seed)
        for a, b in pairs
        for m in ("success", "reward", "walk_minutes")
    ]
    write_csv(out / "comparisons.csv", comparisons)
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return comparisons


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument(
        "--final", action="store_true", help="evaluate on test (frozen settings only)"
    )
    p.add_argument(
        "--scores",
        type=Path,
        help="forecaster probabilities for the split (default: models/forecaster_*)",
    )
    p.add_argument(
        "--rl-model",
        type=Path,
        help="MaskablePPO .zip to evaluate next to the greedy baselines",
    )
    p.add_argument("--lam", type=float, default=0.02)
    p.add_argument("--mu", type=float, default=0.01)
    p.add_argument("--c", type=float, default=0.5)
    p.add_argument("--walk-limit", type=float, default=10)
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--reports", type=Path)
    a = p.parse_args()
    split = "test" if a.final else "tune"
    replay = load_replay(a.data_root, a.project_root, split, a.scores)
    policies = {s: greedy(s, a.lam, a.mu, a.c) for s in SOURCES}
    pairs = [("B3", "B1"), ("B3", "B2")]
    if a.rl_model:
        from train_ppo import load_policy

        policies["RL"] = load_policy(a.rl_model)
        pairs = [("RL", "B3"), ("RL", "B1")] + pairs
    rows = evaluate(replay, policies, a.lam, a.mu, a.c, a.walk_limit)
    manifest = dict(
        split=split,
        requests=len(replay.requests),
        lam=a.lam,
        mu=a.mu,
        c=a.c,
        walk_limit_minutes=a.walk_limit,
        rl_model=str(a.rl_model) if a.rl_model else None,
        bootstrap=a.bootstrap,
        seed=a.seed,
        test_opened=split == "test",
    )
    out = a.reports or a.project_root / f"reports/rl_eval/{split}"
    comparisons = report(rows, out, manifest, pairs, a.bootstrap, a.seed)
    print(
        json.dumps(
            dict(out=str(out), summary=summarize(rows), comparisons=comparisons),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
