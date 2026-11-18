"""Safe PPO bridge for the *current* pickup / return decision only.

A future return recommendation stays provisional B3. Do not feed future replay
features to PPO just to build an initial itinerary.
"""
import json
import importlib.util
import subprocess
import sys

from .core import PROJECT

APP_LAM, APP_MU, APP_C = .02, .01, .5


def observation(slots, phase='pickup', waits=0, elapsed_minutes=0, failures=0, condition=None):
    """31 training features; a conditioned policy also gets (lam/lam_scale, walk/walk_scale)."""
    obs = [0.] * 31
    mask = [False] * 4
    for j, slot in enumerate(slots[:3]):
        mask[j] = slot['valid']
        if not slot['valid']:
            obs[j*9+8] = float(slot.get('tried', False))
            continue
        obs[j*9:j*9+9] = [float(slot['valid']), slot['walk_minutes']/10, slot['horizon']/60,
                          slot['share'], float(slot['empty_now']), slot['p_fail'], slot['p_next'],
                          slot['p_b2'], float(slot.get('tried', False))]
    obs[-4:] = [float(phase == 'return'), waits/2, elapsed_minutes/60, failures/3]
    mask[3] = phase == 'pickup' and waits < 2 and any(mask[:3])
    if condition is not None:
        obs += list(condition)
    return obs, mask


class Policy:
    def __init__(self, root):
        # Prefer the preference-conditioned policy (any walking limit it was trained
        # for); fall back to the fixed 10-minute / lambda=.02 policy.
        conditioned = root / 'models/rl_conditioned/ppo.zip'
        self.path = conditioned if conditioned.exists() else root / 'models/rl_dev/ppo.zip'
        self.manifest = self.path.with_suffix('.json')

    def ready(self):
        return self.path.exists() and self.manifest.exists()

    @staticmethod
    def runtime_ready():
        return all(importlib.util.find_spec(name) is not None for name in ('torch', 'sb3_contrib'))

    def choose(self, slots, walk_limit, phase='pickup', waits=0, elapsed_minutes=0, failures=0):
        if not self.ready():
            raise ValueError('PPO artifact or manifest missing')
        meta = json.loads(self.manifest.read_text(encoding='utf-8'))
        # Do not silently run a policy trained for a different reward/action scope.
        condition = None
        if meta.get('conditioned'):
            if meta.get('observation_size') != 33:
                raise ValueError('PPO observation configuration differs from training')
            if not any(abs(walk_limit - w) < 1e-8 for w in meta.get('walk_choices', [])):
                raise ValueError(f"PPO was trained for walking limits {meta.get('walk_choices')} min; this request uses {walk_limit:g}")
            lams = meta.get('lam_choices', [])
            if not lams or not min(lams) <= APP_LAM <= max(lams):
                raise ValueError('PPO reward configuration differs from the application')
            condition = (APP_LAM / meta['lam_scale'], walk_limit / meta['walk_scale'])
        elif meta.get('observation_size') != 31 or meta.get('walk_limit_minutes') != walk_limit:
            raise ValueError('PPO observation or walking-limit configuration differs from training')
        elif abs(meta.get('lam', -1) - APP_LAM) > 1e-8:
            raise ValueError('PPO reward configuration differs from the application')
        if any(abs(meta.get(k, -1)-v) > 1e-8 for k, v in [('mu', APP_MU), ('c', APP_C)]):
            raise ValueError('PPO reward configuration differs from the application')
        obs, mask = observation(slots, phase, waits, elapsed_minutes, failures, condition)
        if not any(mask):
            raise ValueError('No valid PPO actions')
        result = subprocess.run([sys.executable, '-m', 'backend.policy_worker'],
                                input=json.dumps(dict(path=str(self.path), observation=obs, mask=mask)),
                                text=True, capture_output=True, timeout=15, cwd=PROJECT)
        if result.returncode:
            raise ValueError('PPO runtime failed; install scripts/rl/requirements-ppo.txt in the API environment')
        action = json.loads(result.stdout)['action']
        if not isinstance(action, int) or not 0 <= action < 4 or not mask[action]:
            raise ValueError('PPO returned a forbidden action')
        return action
