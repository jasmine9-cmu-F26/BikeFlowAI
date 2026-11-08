"""Sweep the walking penalty lambda on tune.

For every lambda, retrain PPO with several seeds (the reward changes with lambda),
rerun the greedy baselines with the same lambda on identical requests, and plot
failure rate against extra walking. Training and evaluation are child processes
of train_ppo.py and evaluate.py, so torch never shares a process with another
OpenMP runtime and independent runs proceed in parallel. Outputs go to
reports/rl_eval/lambda_sweep/: one evaluate.py report per lambda, plus
sweep_summary.csv, sweep_comparisons.csv, sweep_manifest.json and frontier.png.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from replay_data import add_request_args, request_provenance

HERE = Path(__file__).resolve().parent
LAMS = (0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32)
SEEDS = (0, 1, 2)


def run_all(commands, jobs):
    env = dict(os.environ, OMP_NUM_THREADS="1")

    def run(cmd):
        done = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if done.returncode:
            raise RuntimeError(
                f"{' '.join(map(str, cmd))} failed:\n{done.stderr[-3000:]}"
            )

    with ThreadPoolExecutor(jobs) as pool:
        list(pool.map(run, commands))


def label(lam):
    return f"{lam:g}"


def split_policy(name, seeds):
    """evaluate.py names one RL model RL and several RL_seed<k>."""
    if name.startswith("RL_seed"):
        return "RL", name[len("RL_seed") :]
    if name == "RL":
        return "RL", str(seeds[0])
    return name, ""


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def collect(reports, lams, seeds):
    summary, comparisons = [], []
    for lam in lams:
        out = reports / f"lam_{label(lam)}"
        for r in read_csv(out / "summary.csv"):
            policy, seed = split_policy(r.pop("policy"), seeds)
            summary.append(dict(lam=label(lam), policy=policy, seed=seed, **r))
        for r in read_csv(out / "comparisons.csv"):
            policy, seed = split_policy(r.pop("policy_a"), seeds)
            comparisons.append(dict(lam=label(lam), policy_a=policy, seed=seed, **r))
    return summary, comparisons


def plot(summary, path):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed; skipping frontier.png", file=sys.stderr)
        return
    lams = sorted({float(r["lam"]) for r in summary})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    panels = (
        (
            axes[0],
            lambda r: float(r["walk_minutes_mean"]),
            "extra walking per rider (min)",
        ),
        (
            axes[1],
            lambda r: float(r["walk_minutes_mean"]) + float(r["wait_minutes_mean"]),
            "walking + waiting per rider (min)",
        ),
    )
    styles = {"B1": "o:", "B2": "s:", "B3": "^-", "RL": "D-"}
    for ax, x_of, xlabel in panels:
        for policy, style in styles.items():
            points = []
            for lam in lams:
                rows = [
                    r
                    for r in summary
                    if r["policy"] == policy and float(r["lam"]) == lam
                ]
                if not rows:
                    continue
                xs = [x_of(r) for r in rows]
                ys = [100 * (1 - float(r["success_rate"])) for r in rows]
                if len(rows) > 1:
                    ax.scatter(xs, ys, s=10, alpha=0.35, color="C3")
                points.append((lam, sum(xs) / len(xs), sum(ys) / len(ys)))
            if not points:
                continue
            line = ax.plot(
                [p[1] for p in points], [p[2] for p in points], style, label=policy
            )[0]
            if policy in ("B3", "RL"):
                # every B3 lambda; RL's cluster near one minute, so only its ends
                shown = points if policy == "B3" else [points[0], points[-1]]
                for lam, x, y in shown:
                    ax.annotate(
                        f"λ={lam:g}",
                        (x, y),
                        textcoords="offset points",
                        xytext=(4, 4),
                        fontsize=7,
                        color=line.get_color(),
                    )
        ax.set_xlabel(xlabel)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("failed trips (%)")
    axes[0].legend()
    fig.suptitle(
        "Tune split: failure vs. rider minutes across λ (RL: mean of seeds, dots per seed)"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--lams", type=float, nargs="+", default=list(LAMS))
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p.add_argument("--steps", type=int, default=300_000)
    p.add_argument("--mu", type=float, default=0.01)
    p.add_argument("--c", type=float, default=0.5)
    p.add_argument("--walk-limit", type=float, default=10)
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    p.add_argument(
        "--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2))
    )
    p.add_argument("--models", type=Path, help="default: models/rl_dev/lambda_sweep")
    p.add_argument("--reports", type=Path)
    p.add_argument(
        "--skip-train", action="store_true", help="reuse the models already in --models"
    )
    add_request_args(p)
    a = p.parse_args()
    lams, seeds = sorted(set(a.lams)), sorted(set(a.seeds))
    models = a.models or a.data_root / "models/rl_dev/lambda_sweep"
    reports = a.reports or a.project_root / "reports/rl_eval/lambda_sweep"
    common = [
        "--data-root",
        str(a.data_root),
        "--project-root",
        str(a.project_root),
        "--mu",
        str(a.mu),
        "--c",
        str(a.c),
        "--walk-limit",
        str(a.walk_limit),
        "--requests",
        a.requests,
        "--demand-scale",
        str(a.demand_scale),
        "--request-seed",
        str(a.request_seed),
    ]

    def model(lam, seed):
        return models / f"lam_{label(lam)}_seed_{seed}.zip"

    if not a.skip_train:
        run_all(
            [
                [
                    sys.executable,
                    str(HERE / "train_ppo.py"),
                    *common,
                    "--lam",
                    str(lam),
                    "--seed",
                    str(seed),
                    "--steps",
                    str(a.steps),
                    "--out",
                    str(model(lam, seed)),
                ]
                for lam in lams
                for seed in seeds
            ],
            a.jobs,
        )
    run_all(
        [
            [
                sys.executable,
                str(HERE / "evaluate.py"),
                *common,
                "--lam",
                str(lam),
                *[x for s in seeds for x in ("--rl-model", str(model(lam, s)))],
                "--reports",
                str(reports / f"lam_{label(lam)}"),
                "--bootstrap",
                str(a.bootstrap),
                "--seed",
                str(a.seed),
            ]
            for lam in lams
        ],
        a.jobs,
    )
    summary, comparisons = collect(reports, lams, seeds)
    write_csv(reports / "sweep_summary.csv", summary)
    write_csv(reports / "sweep_comparisons.csv", comparisons)
    (reports / "sweep_manifest.json").write_text(
        json.dumps(
            dict(
                split="tune",
                lams=lams,
                seeds=seeds,
                steps=a.steps,
                mu=a.mu,
                c=a.c,
                walk_limit_minutes=a.walk_limit,
                **request_provenance(a),
                models=str(models),
                bootstrap=a.bootstrap,
                seed=a.seed,
                test_opened=False,
            ),
            indent=2,
        )
        + "\n"
    )
    plot(summary, reports / "frontier.png")
    print(json.dumps(dict(out=str(reports), runs=len(lams) * len(seeds)), indent=2))


if __name__ == "__main__":
    main()
