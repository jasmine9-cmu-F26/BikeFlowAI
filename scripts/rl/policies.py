"""Myopic greedy policies: one scoring rule, three failure-probability sources.

A slot is worth its expected one-step reward, 1 - (1 + c) * p_fail - lam * walk.
Waiting is worth the best slot's value with the probability for arriving ten
minutes later, minus mu * 10. B1 uses current emptiness (so waiting never
helps), B2 the training-period availability rate, B3 the calibrated forecaster.
"""

import numpy as np

from replay_env import STEP, WAIT

SOURCES = ("B1", "B2", "B3")


def failure_probabilities(slot, source):
    """(p now, p ten minutes later or None) for one valid slot."""
    if source == "B1":
        p = float(slot["empty_now"])
        return p, p
    if source == "B2":
        p = slot["p_b2"] if slot["p_b2"] is not None else float(slot["empty_now"])
        return p, slot["p_b2_next"] if slot["p_b2_next"] is not None else p
    if source == "B3":
        return slot["p_forecast"], slot["p_forecast_next"]
    raise ValueError(f"unknown probability source {source}; expected one of {SOURCES}")


def greedy(source, lam, mu, c):
    if source not in SOURCES:
        raise ValueError(
            f"unknown probability source {source}; expected one of {SOURCES}"
        )

    def act(env, obs=None):
        mask = env.action_masks()
        scores = np.full(len(mask), -np.inf)
        wait_value = -np.inf
        for j, slot in enumerate(env.slots()):
            if not slot["valid"]:
                continue
            p, p_next = failure_probabilities(slot, source)
            scores[j] = 1 - (1 + c) * p - lam * slot["walk_minutes"]
            if p_next is not None:
                wait_value = max(
                    wait_value, 1 - (1 + c) * p_next - lam * slot["walk_minutes"]
                )
        if mask[WAIT]:
            scores[WAIT] = (
                wait_value - mu * STEP / 60 if np.isfinite(wait_value) else -1e9
            )
        return int(np.argmax(scores))

    return act
