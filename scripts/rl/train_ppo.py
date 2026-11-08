"""Train MaskablePPO on the training-week replay (weeks 2+, forward-chained scores).

Needs scripts/rl/requirements-ppo.txt. Evaluate the saved model on tune with
evaluate.py --rl-model; test only once, with --final and frozen settings.
"""

import argparse
import json
import time
from pathlib import Path

from replay_env import OBS_SIZE, ReplayEnv

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
    replay, out, steps, lam=0.02, mu=0.01, c=0.5, walk_limit=10, seed=0, provenance=None
):
    from sb3_contrib import MaskablePPO

    env = ReplayEnv(replay, lam=lam, mu=mu, c=c, walk_limit=walk_limit, seed=seed)
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
                lam=lam,
                mu=mu,
                c=c,
                walk_limit_minutes=walk_limit,
                seed=seed,
                observation_size=OBS_SIZE,
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
    p.add_argument("--walk-limit", type=float, default=10)
    p.add_argument("--seed", type=int, default=0)
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
    out = a.out or a.data_root / "models/rl_dev/ppo.zip"
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
    )
    print(
        json.dumps(dict(out=str(out), training_requests=len(replay.requests)), indent=2)
    )


if __name__ == "__main__":
    main()
