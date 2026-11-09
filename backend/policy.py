"""Safe PPO bridge for the *current* pickup / return decision only.

A future return recommendation stays provisional B3. Do not feed future replay
features to PPO just to build an initial itinerary.
"""
import json
import importlib.util
import subprocess
import sys

from .core import PROJECT


def observation(slots, phase='pickup', waits=0, elapsed_minutes=0, failures=0):
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
    return obs, mask


class Policy:
    def __init__(self, root):
        self.path = root / 'models/rl_dev/ppo.zip'
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
        if meta.get('observation_size') != 31 or meta.get('walk_limit_minutes') != walk_limit:
            raise ValueError('PPO observation or walking-limit configuration differs from training')
        if any(abs(meta.get(k, -1)-v) > 1e-8 for k, v in [('lam', .02), ('mu', .01), ('c', .5)]):
            raise ValueError('PPO reward configuration differs from the application')
        obs, mask = observation(slots, phase, waits, elapsed_minutes, failures)
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
