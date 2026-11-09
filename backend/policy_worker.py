"""One-shot CPU PPO inference in a separate process from LightGBM.

Input is a decision-only observation and mask. No data / outcome paths are read.
"""
import contextlib
import json
import sys


def main():
    request = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        from sb3_contrib import MaskablePPO
        policy = MaskablePPO.load(request['path'], device='cpu')
        action, _ = policy.predict(np.asarray(request['observation'], dtype=np.float32),
                                   action_masks=np.asarray(request['mask'], dtype=bool), deterministic=True)
    print(json.dumps({'action': int(action)}))


if __name__ == '__main__':
    main()
