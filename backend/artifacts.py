"""Verify and materialize the small, versioned application-only data bundle.

No training, network access, pickle loading or final-test access occurs here.
Explicit external roots always take precedence over this bundled default.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

from .core import PROJECT

BUNDLE = PROJECT / 'artifacts/m3-demo.zip'
BUNDLE_MANIFEST = PROJECT / 'artifacts/m3-demo.json'
DEFAULT_EXTERNAL = Path.home() / 'Documents/BikeFlowAI-data/divvy/chicago_historical_2021_sample'


def materialize_bundle(bundle=BUNDLE, manifest_path=BUNDLE_MANIFEST, cache_root=None):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    digest = hashlib.sha256(Path(bundle).read_bytes()).hexdigest()
    if digest != manifest['sha256']:
        raise ValueError('Bundled demo checksum mismatch; restore artifacts/m3-demo.zip from Git.')
    cache_root = Path(cache_root or PROJECT / '.local/data').resolve()
    target = cache_root / ('m3-demo-' + digest[:16])
    marker = target / '.bundle-sha256'
    required = manifest['required_files']

    def complete():
        return marker.is_file() and marker.read_text(encoding='utf-8').strip() == digest and all((target / f).is_file() for f in required)

    if complete():
        return target
    if target.exists():
        raise ValueError('Demo cache is incomplete; remove only this cache directory and restart: ' + str(target))
    cache_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        if len(members) != manifest['file_count'] or sum(m.file_size for m in members) > 32 * 1024 * 1024:
            raise ValueError('Unexpected bundled demo size or file count.')
        for m in members:
            name = PurePosixPath(m.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in m.filename or ':' in m.filename:
                raise ValueError('Unsafe path in demo bundle.')
            if (m.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Symlinks are not allowed in the demo bundle.')
        with tempfile.TemporaryDirectory(prefix='extract-', dir=cache_root) as temp:
            staging = Path(temp) / 'data'
            staging.mkdir()
            archive.extractall(staging)
            if not all((staging / f).is_file() for f in required):
                raise ValueError('The demo bundle is missing required serving files.')
            (staging / '.bundle-sha256').write_text(digest + '\n', encoding='utf-8')
            try:
                staging.rename(target)
            except FileExistsError:
                if not complete():
                    raise
    return target


def resolve_data_root(explicit=None):
    if explicit is not None:
        return Path(explicit), 'explicit'
    configured = os.environ.get('BIKEFLOW_DATA_ROOT', '').strip()
    if configured:
        return Path(configured).expanduser(), 'environment'
    # Compose optionally mounts a full external package here. The empty default
    # mount must not disable the versioned bundle included in the image.
    mounted = os.environ.get('BIKEFLOW_MOUNTED_DATA_ROOT', '').strip()
    if mounted and (Path(mounted) / 'models/forecaster_v0_m3/manifest.json').is_file():
        return Path(mounted), 'mounted'
    if BUNDLE.is_file() and BUNDLE_MANIFEST.is_file():
        return materialize_bundle(), 'bundled_m3_tune'
    return DEFAULT_EXTERNAL, 'default_external'
