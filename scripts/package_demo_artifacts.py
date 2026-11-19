"""Package only serving weights, B2 and tune features/labels for a Git clone.

Never includes raw station polls/trips, training prediction tables, calibration
or final-test data. Run with --source <team-artifact.zip>.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
PREFIX = 'processed/final_pipeline_v1/'
MODEL_FILES = ['models/forecaster_v0_m3/' + name for name in ('manifest.json', 'bike_lgbm.txt', 'dock_lgbm.txt')]
REQUIRED = MODEL_FILES + [PREFIX + 'B2/heldout_training_fit_rates.parquet', 'models/rl_dev/ppo.zip', 'models/rl_dev/ppo.json']
CONDITIONED = ['models/rl_conditioned/ppo.zip', 'models/rl_conditioned/ppo.json']


def selected(name):
    return name in REQUIRED or name in CONDITIONED or (name.startswith((PREFIX + 'features/', PREFIX + 'labels/')) and name.endswith('_tune.parquet'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=PROJECT / 'artifacts/m3-demo.zip')
    parser.add_argument('--version', default='m3-demo-v1')
    parser.add_argument('--conditioned-policy', type=Path,
                        help='preference-conditioned PPO .zip (with its .json) to serve as models/rl_conditioned/; '
                             'the app prefers it over the fixed 10-minute rl_dev policy')
    args = parser.parse_args()
    extra = {}
    if args.conditioned_policy:
        meta = json.loads(args.conditioned_policy.with_suffix('.json').read_text(encoding='utf-8'))
        if not meta.get('conditioned') or meta.get('observation_size') != 33:
            parser.error('--conditioned-policy must be trained with train_ppo.py --conditioned')
        extra = {CONDITIONED[0]: args.conditioned_policy.read_bytes(),
                 CONDITIONED[1]: args.conditioned_policy.with_suffix('.json').read_bytes()}
    if args.output.exists():
        parser.error('Output exists; choose a new versioned output instead of overwriting.')
    with zipfile.ZipFile(args.source) as source:
        names = sorted({n for n in source.namelist() if selected(n)} | set(extra))
        if not set(REQUIRED) <= set(names) or len([n for n in names if '/features/' in n]) != 32 or len([n for n in names if '/labels/' in n]) != 32:
            parser.error('Expected forecaster/PPO weights, B2 and 32 tune feature/label files.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
            for name in names:
                # Fixed metadata makes the binary reproducible across platforms.
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 9, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                out.writestr(info, extra[name] if name in extra else source.read(name))
    manifest = dict(version=args.version, model_version='forecaster_v0_m3', scope='32 app stations; tune replay only',
                    replay_start='2021-07-12T01:00:00-05:00', replay_end_exclusive='2021-07-26T00:00:00-05:00',
                    default_time='2021-07-20T08:06:00-05:00', sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                    source_archive_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                    file_count=len(names), size_bytes=args.output.stat().st_size, required_files=names)
    args.output.with_suffix('.json').write_text(json.dumps(manifest, indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in manifest.items() if k != 'required_files'}))


if __name__ == '__main__':
    main()
