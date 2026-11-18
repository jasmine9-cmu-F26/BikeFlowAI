"""Train MaskablePPO on the training-week replay (weeks 2+, forward-chained scores).

Needs scripts/rl/requirements-ppo.txt. Evaluate the saved model on tune with
evaluate.py --rl-model; test only once, with --final and frozen settings.
"""

import argparse
import json
import time
from pathlib import Path

from replay_env import (
    CONDITIONED_OBS_SIZE,
    LAM_SCALE,
    OBS_SIZE,
    WALK_SCALE,
    ReplayEnv,
)

# Preference-conditioned defaults: the lambda range where policies still differ
# (reports/rl_eval/lambda_sweep) and the app's walking-limit choices.
LAM_CHOICES = (0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16)
WALK_CHOICES = (5, 10, 15)

PPO_SETTINGS = dict(
    n_steps=2048,
    batch_size=256,
    n_epochs=10,
    gamma=1.0,
    gae_lambda=0.95,
    learning_rate=3e-4,
    ent_coef=0.01,
    clip_range=0.2,
)


def train(
    replay,
    out,
    steps,
    lam=0.02,
    mu=0.01,
    c=0.5,
    walk_limit=10,
    seed=0,
    provenance=None,
    conditioned=False,
    lam_choices=LAM_CHOICES,
    walk_choices=WALK_CHOICES,
    f=0.0,
):
    """Fixed (lam, walk_limit), or with `conditioned` one policy sampling both per episode."""
    from sb3_contrib import MaskablePPO

    env = ReplayEnv(
        replay,
        lam=lam,
        mu=mu,
        c=c,
        walk_limit=walk_limit,
        seed=seed,
        conditioned=conditioned,
        lam_choices=lam_choices if conditioned else None,
        walk_choices=walk_choices if conditioned else None,
        f=f,
    )
    model = MaskablePPO(
        "MlpPolicy", env, seed=seed, verbose=0, device="cpu", **PPO_SETTINGS
    )
    started = time.time()
    model.learn(total_timesteps=steps)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save(out)
    out.with_suffix(".json").write_text(
        json.dumps(
            dict(
                steps=steps,
                lam=None if conditioned else lam,
                mu=mu,
                c=c,
                f=f,
                walk_limit_minutes=None if conditioned else walk_limit,
                conditioned=conditioned,
                **(
                    dict(
                        lam_choices=list(lam_choices),
                        walk_choices=list(walk_choices),
                        lam_scale=LAM_SCALE,
                        walk_scale=WALK_SCALE,
                    )
                    if conditioned
                    else {}
                ),
                seed=seed,
                observation_size=CONDITIONED_OBS_SIZE if conditioned else OBS_SIZE,
                training_requests=len(replay.requests),
                versions=sorted({q.version for q in replay.requests}),
                **(provenance or {}),
                ppo=PPO_SETTINGS,
                seconds=round(time.time() - started, 1),
            ),
            indent=2,
        )
        + "\n"
    )
    return model


def load_policy(path):
    from sb3_contrib import MaskablePPO

    model = MaskablePPO.load(Path(path), device="cpu")

    def act(env, obs):
        action, _ = model.predict(
            obs, action_masks=env.action_masks(), deterministic=True
        )
        return int(action)

    return act


def main():
    from replay_data import add_request_args, load_replay, request_provenance

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument(
        "--scores",
        type=Path,
        help="forward-chained training scores (default: models/forecaster_dev/...)",
    )
    p.add_argument("--steps", type=int, default=300_000)
    p.add_argument("--lam", type=float, default=0.02)
    p.add_argument("--mu", type=float, default=0.01)
    p.add_argument("--c", type=float, default=0.5)
    p.add_argument(
        "--f", type=float, default=0.0, help="penalty per failed attempt (0 = M3 reward)"
    )
    p.add_argument("--walk-limit", type=float, default=10)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--conditioned",
        action="store_true",
        help="one policy for every rider: sample lambda and the walking limit per "
        "episode and give both to the policy (--lam / --walk-limit are then ignored)",
    )
    p.add_argument("--lam-choices", type=float, nargs="+", default=list(LAM_CHOICES))
    p.add_argument("--walk-choices", type=float, nargs="+", default=list(WALK_CHOICES))
    p.add_argument("--out", type=Path)
    add_request_args(p)
    a = p.parse_args()
    replay = load_replay(
        a.data_root,
        a.project_root,
        "train",
        a.scores,
        a.requests,
        a.demand_scale,
        a.request_seed,
    )
    out = a.out or a.data_root / (
        "models/rl_conditioned/ppo.zip" if a.conditioned else "models/rl_dev/ppo.zip"
    )
    train(
        replay,
        out,
        a.steps,
        a.lam,
        a.mu,
        a.c,
        a.walk_limit,
        a.seed,
        provenance=request_provenance(a),
        conditioned=a.conditioned,
        lam_choices=a.lam_choices,
        walk_choices=a.walk_choices,
        f=a.f,
    )
    print(
        json.dumps(dict(out=str(out), training_requests=len(replay.requests)), indent=2)
    )


if __name__ == "__main__":
    main()
