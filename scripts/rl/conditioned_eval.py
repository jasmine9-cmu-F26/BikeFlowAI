"""Evaluate one preference-conditioned PPO across riders' walking limits and lambdas.

The conditioned policy (train_ppo.py --conditioned) is a single model per seed
that reads lambda and the walking limit from its observation. For every
(walk limit, lambda) cell this reruns evaluate.py on the same tune requests:
B1/B2/B3 greedy with that lambda next to the conditioned RL seeds. Outputs go
to reports/rl_eval/conditioned/: one evaluate.py report per cell, plus
grid_summary.csv, grid_comparisons.csv, grid_manifest.json and frontier.png.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from replay_data import add_request_args, request_provenance
from sweep import HERE, label, read_csv, run_all, split_policy, write_csv

WALKS = (5, 10, 15)
LAMS = (0.0, 0.01, 0.02, 0.04, 0.08)


def cell(walk, lam):
    return f"walk_{label(walk)}_lam_{label(lam)}"


def collect(reports, walks, lams, seeds):
    summary, comparisons = [], []
    for walk in walks:
        for lam in lams:
            out = reports / cell(walk, lam)
            for r in read_csv(out / "summary.csv"):
                policy, seed = split_policy(r.pop("policy"), seeds)
                summary.append(
                    dict(walk=label(walk), lam=label(lam), policy=policy, seed=seed, **r)
                )
            for r in read_csv(out / "comparisons.csv"):
                policy, seed = split_policy(r.pop("policy_a"), seeds)
                comparisons.append(
                    dict(
                        walk=label(walk), lam=label(lam), policy_a=policy, seed=seed, **r
                    )
                )
    return summary, comparisons


def plot(summary, walks, path):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed; skipping frontier.png", file=sys.stderr)
        return
    fig, axes = plt.subplots(1, len(walks), figsize=(5 * len(walks), 4.3), sharey=True)
    styles = {"B1": "o:", "B2": "s:", "B3": "^-", "RL": "D-"}
    for ax, walk in zip(axes, walks):
        rows = [r for r in summary if r["walk"] == label(walk)]
        for policy, style in styles.items():
            points = []
            for lam in sorted({float(r["lam"]) for r in rows}):
                mine = [
                    r for r in rows if r["policy"] == policy and float(r["lam"]) == lam
                ]
                if not mine:
                    continue
                xs = [float(r["walk_minutes_mean"]) for r in mine]
                ys = [100 * (1 - float(r["success_rate"])) for r in mine]
                if len(mine) > 1:
                    ax.scatter(xs, ys, s=10, alpha=0.35, color="C3")
                points.append((lam, sum(xs) / len(xs), sum(ys) / len(ys)))
            if points:
                line = ax.plot(
                    [p[1] for p in points], [p[2] for p in points], style, label=policy
                )[0]
                if policy in ("B3", "RL"):
                    for lam, x, y in (points[0], points[-1]):
                        ax.annotate(
                            f"λ={lam:g}",
                            (x, y),
                            textcoords="offset points",
                            xytext=(4, 4),
                            fontsize=7,
                            color=line.get_color(),
                        )
        ax.set_title(f"walking limit {label(walk)} min")
        ax.set_xlabel("extra walking per rider (min)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("failed trips (%)")
    axes[0].legend()
    fig.suptitle(
        "Tune split: one conditioned PPO per seed vs. greedy baselines "
        "(RL: mean of seeds, dots per seed)"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument(
        "--rl-model",
        type=Path,
        action="append",
        default=[],
        help="conditioned MaskablePPO .zip; repeat for several seeds "
        "(default: models/rl_conditioned/seed*/ppo.zip)",
    )
    p.add_argument("--walks", type=float, nargs="+", default=list(WALKS))
    p.add_argument("--lams", type=float, nargs="+", default=list(LAMS))
    p.add_argument("--mu", type=float, default=0.01)
    p.add_argument("--c", type=float, default=0.5)
    p.add_argument(
        "--f", type=float, default=0.0, help="penalty per failed attempt (0 = M3 reward)"
    )
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    p.add_argument(
        "--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2))
    )
    p.add_argument("--reports", type=Path)
    add_request_args(p)
    a = p.parse_args()
    models = a.rl_model or sorted(
        (a.data_root / "models/rl_conditioned").glob("seed*/ppo.zip")
    )
    if not models:
        p.error("no conditioned models; run train_ppo.py --conditioned first")
    metas = [json.loads(Path(m).with_suffix(".json").read_text()) for m in models]
    if not all(m.get("conditioned") for m in metas):
        p.error("every --rl-model must be trained with --conditioned")
    seeds = sorted(m["seed"] for m in metas)
    walks, lams = sorted(set(a.walks)), sorted(set(a.lams))
    reports = a.reports or a.project_root / "reports/rl_eval/conditioned"
    common = [
        "--data-root",
        str(a.data_root),
        "--project-root",
        str(a.project_root),
        "--mu",
        str(a.mu),
        "--c",
        str(a.c),
        "--f",
        str(a.f),
        "--requests",
        a.requests,
        "--demand-scale",
        str(a.demand_scale),
        "--request-seed",
        str(a.request_seed),
        "--bootstrap",
        str(a.bootstrap),
        "--seed",
        str(a.seed),
        *[x for m in models for x in ("--rl-model", str(m))],
    ]
    run_all(
        [
            [
                sys.executable,
                str(HERE / "evaluate.py"),
                *common,
                "--walk-limit",
                str(walk),
                "--lam",
                str(lam),
                "--reports",
                str(reports / cell(walk, lam)),
            ]
            for walk in walks
            for lam in lams
        ],
        a.jobs,
    )
    summary, comparisons = collect(reports, walks, lams, seeds)
    write_csv(reports / "grid_summary.csv", summary)
    write_csv(reports / "grid_comparisons.csv", comparisons)
    (reports / "grid_manifest.json").write_text(
        json.dumps(
            dict(
                split="tune",
                walks=walks,
                lams=lams,
                seeds=seeds,
                models=[str(m) for m in models],
                training=[
                    {
                        k: m.get(k, 0.0)
                        for k in ("steps", "lam_choices", "walk_choices", "seed", "f")
                    }
                    for m in metas
                ],
                mu=a.mu,
                c=a.c,
                f=a.f,
                **request_provenance(a),
                bootstrap=a.bootstrap,
                seed=a.seed,
                test_opened=False,
            ),
            indent=2,
        )
        + "\n"
    )
    plot(summary, walks, reports / "frontier.png")
    print(json.dumps(dict(out=str(reports), cells=len(walks) * len(lams)), indent=2))


if __name__ == "__main__":
    main()
